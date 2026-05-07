from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
import pyodbc
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.services.ai.gemini_client import InMemoryTTLCache

logger = logging.getLogger("app.integrations.jde")


class JDEConnectorError(Exception):
    pass


class BaseJDEConnector(ABC):
    @abstractmethod
    def get_gl_accounts(self, company_id: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_ap_invoices(self, vendor_id: str | None = None, from_date: date | None = None, to_date: date | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_vendors(self, search_term: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_customers(self, search_term: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_purchase_orders(self, po_number: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def create_po(self, po_data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def post_invoice(self, invoice_data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_journal_entry(self, entry_data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_cost_centers(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_currencies(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class JDEDataMapper:
    STATUS_MAP = {"A": "APPROVED", "P": "POSTED", "D": "DRAFT", "V": "VOID"}

    @staticmethod
    def map_vendor(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "vendor_number": record.get("AN8") or record.get("vendor_number"),
            "vendor_name": record.get("ALPH") or record.get("vendor_name"),
            "tax_id": record.get("TXID") or record.get("tax_id"),
        }

    @staticmethod
    def map_invoice(record: dict[str, Any]) -> dict[str, Any]:
        amount = record.get("amount") or record.get("AEXP") or 0
        return {
            "invoice_number": record.get("invoice_number") or record.get("DOC"),
            "vendor_id": record.get("vendor_id") or record.get("AN8"),
            "amount": float(amount),
            "currency": record.get("currency") or record.get("CRCD") or "USD",
            "status": JDEDataMapper.STATUS_MAP.get(record.get("status") or record.get("ST"), record.get("status", "UNKNOWN")),
        }

    @staticmethod
    def map_gl_account(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "account_number": record.get("account_number") or record.get("OBJ"),
            "account_name": record.get("account_name") or record.get("DL01"),
            "account_type": record.get("account_type") or record.get("LT"),
        }


class JDERestConnector(BaseJDEConnector):
    def __init__(self) -> None:
        self.base_url = settings.jde_api_base_url.rstrip("/") if settings.jde_api_base_url else ""
        self.device_name = "AI-ERP-COPILOT"
        self.client = httpx.Client(
            timeout=settings.jde_api_timeout_seconds,
            follow_redirects=True,
            headers={"Accept-Encoding": "identity"},
        )
        self.cache = InMemoryTTLCache(settings.jde_cache_gl_ttl_seconds)
        self.token: str | None = settings.jde_api_token.get_secret_value() if settings.jde_api_token else None
        self.token_expires_at: datetime | None = None

    def _is_ais_context(self) -> bool:
        return "/jderest" in self.base_url.lower()

    def _headers(self) -> dict[str, str]:
        if self._is_ais_context():
            headers: dict[str, str] = {"jde-AIS-Auth-Device": self.device_name}
            if self.token:
                headers["jde-AIS-Auth"] = self.token
            return headers
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if settings.jde_api_username and settings.jde_api_password and settings.jde_api_password.get_secret_value():
            token = base64.b64encode(
                f"{settings.jde_api_username}:{settings.jde_api_password.get_secret_value()}".encode("utf-8")
            ).decode("utf-8")
            return {"Authorization": f"Basic {token}"}
        return {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type(httpx.HTTPError), reraise=True)
    def _request(self, method: str, path: str, **kwargs):
        if not self.token:
            if settings.jde_oauth_client_id and settings.jde_oauth_client_secret and settings.jde_oauth_token_url:
                self._authenticate()
            elif settings.jde_api_username and settings.jde_api_password and settings.jde_api_password.get_secret_value():
                self._authenticate_with_password()
        started = datetime.utcnow()
        response = self.client.request(method, f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        if response.status_code == 401:
            if settings.jde_oauth_client_id and settings.jde_oauth_client_secret and settings.jde_oauth_token_url:
                self._authenticate(force=True)
            else:
                self._authenticate_with_password(force=True)
            response = self.client.request(method, f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        response.raise_for_status()
        logger.info("JDE REST call method=%s path=%s latency_ms=%.2f", method, path, (datetime.utcnow() - started).total_seconds() * 1000)
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    def _authenticate(self, force: bool = False) -> None:
        if not force and self.token and self.token_expires_at and self.token_expires_at > datetime.utcnow() + timedelta(minutes=5):
            return
        if not settings.jde_oauth_token_url:
            raise JDEConnectorError("JD Edwards OAuth token URL is not configured.")
        response = self.client.post(
            settings.jde_oauth_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.jde_oauth_client_id,
                "client_secret": settings.jde_oauth_client_secret.get_secret_value() if settings.jde_oauth_client_secret else "",
            },
        )
        response.raise_for_status()
        payload = response.json()
        self.token = payload.get("access_token")
        self.token_expires_at = datetime.utcnow() + timedelta(seconds=int(payload.get("expires_in", 3600)))

    def _authenticate_with_password(self, force: bool = False) -> None:
        if not force and self.token and self.token_expires_at and self.token_expires_at > datetime.utcnow() + timedelta(minutes=5):
            return
        if not settings.jde_api_username or not settings.jde_api_password or not settings.jde_api_password.get_secret_value():
            raise JDEConnectorError("JD Edwards username/password credentials are not configured.")

        candidates = []
        if self.base_url:
            candidates.append(f"{self.base_url}/tokenrequest")
            candidates.append(f"{self.base_url.rstrip('/v3')}/tokenrequest")
            if "/jderest" in self.base_url:
                root = self.base_url.split("/jderest", 1)[0]
                candidates.append(f"{root}/jderest/tokenrequest")

        payload = {
            "username": settings.jde_api_username,
            "password": settings.jde_api_password.get_secret_value(),
            "environment": settings.jde_environment or "DV920",
            "role": settings.jde_role or "*ALL",
        }

        last_error: Exception | None = None
        for url in candidates:
            try:
                response = self.client.post(url, json=payload, headers={"jde-AIS-Auth-Device": self.device_name})
                response.raise_for_status()
                data = response.json()
                token = (
                    data.get("token")
                    or data.get("jdeToken")
                    or (data.get("userInfo") or {}).get("token")
                    or (data.get("userInfo") or {}).get("jdeToken")
                )
                if token:
                    self.token = token
                    self.token_expires_at = datetime.utcnow() + timedelta(hours=1)
                    logger.info("JD Edwards password authentication succeeded using %s", url)
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        raise JDEConnectorError(f"JD Edwards password authentication failed. Last error: {last_error}")

    def _normalize_orchestration_items(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            if isinstance(payload.get("items"), list):
                return [item for item in payload["items"] if isinstance(item, dict)]
            if isinstance(payload.get("udoObjects"), list):
                items: list[dict[str, Any]] = []
                for group in payload["udoObjects"]:
                    if not isinstance(group, dict):
                        continue
                    group_items = group.get("items")
                    if isinstance(group_items, list):
                        items.extend(item for item in group_items if isinstance(item, dict))
                if items:
                    return items
            for value in payload.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def _list_orchestrations(self) -> list[dict[str, Any]]:
        payload = self._request("POST", "/studio/orchestrator/getAllOrchestrations", json={})
        return self._normalize_orchestration_items(payload)

    def _candidate_orchestration_names(
        self,
        orchestrations: list[dict[str, Any]],
        preferred_names: list[str],
        keywords: list[str],
    ) -> list[str]:
        name_map: dict[str, str] = {}
        for item in orchestrations:
            name = str(item.get("name") or "").strip()
            if name:
                name_map[name.lower()] = name

        ordered_candidates: list[str] = []
        seen: set[str] = set()

        def add_candidate(candidate: str) -> None:
            lowered = candidate.lower()
            if lowered not in seen:
                seen.add(lowered)
                ordered_candidates.append(candidate)

        for preferred in preferred_names:
            selected = name_map.get(preferred.lower())
            if selected:
                add_candidate(selected)

        lowered_keywords = [kw.lower() for kw in keywords]
        for item in orchestrations:
            name = str(item.get("name") or "")
            description = str(item.get("description") or "")
            haystack = f"{name} {description}".lower()
            if any(keyword in haystack for keyword in lowered_keywords):
                add_candidate(name)
        return ordered_candidates

    def _run_studio_orchestration(
        self,
        *,
        action_label: str,
        payload: dict[str, Any],
        preferred_names: list[str],
        keywords: list[str],
    ) -> dict[str, Any]:
        orchestrations = self._list_orchestrations()
        candidates = self._candidate_orchestration_names(orchestrations, preferred_names, keywords)
        if not candidates:
            raise JDEConnectorError(
                f"No matching JD Edwards orchestration found for '{action_label}'. "
                "Please configure a runnable orchestration in the target tenant."
            )

        failures: list[str] = []
        for selected_name in candidates:
            try:
                result = self._request(
                    "POST",
                    f"/studio/client/orchestrator/{quote(selected_name, safe='')}",
                    json=payload,
                )
                return {
                    "orchestration": selected_name,
                    "action": action_label,
                    "input": payload,
                    "output": result,
                }
            except httpx.HTTPStatusError as exc:
                failures.append(f"{selected_name}: HTTP {exc.response.status_code}")
                continue
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{selected_name}: {exc}")
                continue

        failure_summary = "; ".join(failures[:5])
        raise JDEConnectorError(
            f"All matching JD Edwards orchestrations failed for '{action_label}'. "
            f"Sample failures: {failure_summary}"
        )

    def _run_v3_orchestration(self, orchestration_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            "POST",
            f"/v3/orchestrator/{quote(orchestration_name, safe='')}",
            json=payload,
        )
        return {
            "orchestration": orchestration_name,
            "action": "create_po",
            "input": payload,
            "output": result,
        }

    def _to_po_orchestration_payload(self, po_data: dict[str, Any]) -> dict[str, Any]:
        branch_plant = (
            po_data.get("branch_plant")
            or po_data.get("business_unit")
            or po_data.get("branchPlant")
            or "M30"
        )

        supplier = (
            po_data.get("supplier")
            or po_data.get("supplier_number")
            or po_data.get("vendor_number")
            or po_data.get("vendor_id")
            or po_data.get("vendor_name")
            or ""
        )

        lines: list[dict[str, Any]] = []
        for line in po_data.get("line_items", []):
            item_number = line.get("item_number") or line.get("item_code") or line.get("sku") or line.get("description")
            quantity = line.get("quantity") or line.get("qty") or line.get("ordered_quantity") or 1
            if item_number:
                lines.append({"Item_Number": str(item_number), "Quantity_Ordered": str(quantity)})

        if not lines:
            lines.append({"Item_Number": "220", "Quantity_Ordered": "1"})

        payload = {
            "Branch_Plant": str(branch_plant),
            "Supplier": str(supplier),
            "GridIn_1_3": lines,
            "P4310_Version": po_data.get("p4310_version") or "ZJDE0001",
            "Previous_Order": po_data.get("previous_order") or "",
            "Previous_Order_Type": po_data.get("previous_order_type") or "OP",
            "popdfFileName": po_data.get("pdf_file_name") or "AIERP_PO",
        }
        return payload

    def get_gl_accounts(self, company_id: str | None = None) -> list[dict[str, Any]]:
        cache_key = f"gl:{company_id}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        payload = self._request("GET", "/gl/accounts", params={"company_id": company_id} if company_id else None)
        mapped = [JDEDataMapper.map_gl_account(item) for item in payload.get("items", payload)]
        self.cache.set(cache_key, mapped)
        return mapped

    def get_ap_invoices(self, vendor_id: str | None = None, from_date: date | None = None, to_date: date | None = None) -> list[dict[str, Any]]:
        params = {"vendor_id": vendor_id, "from_date": from_date.isoformat() if from_date else None, "to_date": to_date.isoformat() if to_date else None}
        payload = self._request("GET", "/ap/invoices", params={k: v for k, v in params.items() if v is not None})
        return [JDEDataMapper.map_invoice(item) for item in payload.get("items", payload)]

    def get_vendors(self, search_term: str | None = None) -> list[dict[str, Any]]:
        cache_key = f"vendors:{search_term}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        payload = self._request("GET", "/vendors", params={"search": search_term} if search_term else None)
        mapped = [JDEDataMapper.map_vendor(item) for item in payload.get("items", payload)]
        self.cache.set(cache_key, mapped)
        return mapped

    def get_customers(self, search_term: str | None = None) -> list[dict[str, Any]]:
        payload = self._request("GET", "/customers", params={"search": search_term} if search_term else None)
        return payload.get("items", payload)

    def get_purchase_orders(self, po_number: str | None = None) -> list[dict[str, Any]]:
        payload = self._request("GET", "/purchase-orders", params={"po_number": po_number} if po_number else None)
        return payload.get("items", payload)

    def create_po(self, po_data: dict[str, Any]) -> dict[str, Any]:
        if self._is_ais_context():
            mapped_payload = self._to_po_orchestration_payload(po_data)
            try:
                return self._run_v3_orchestration("ORCH_CH210326_PO Entry Print and send doc to supp", mapped_payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Primary PO orchestration failed, falling back. reason=%s", exc)
                fallback_result = self._run_studio_orchestration(
                    action_label="create_po",
                    payload=mapped_payload,
                    preferred_names=[
                        "ORCH_CH250326_Print PO",
                        "JDE_ORCH_43_Retrieve_Purchase_Order_Data",
                        "JDE_ORCH_43_Update_Purchase_Order_Status",
                    ],
                    keywords=["purchase order", "po", "supplier", "procure"],
                )
                fallback_result["fallback_from"] = "ORCH_CH210326_PO Entry Print and send doc to supp"
                fallback_result["warning"] = f"Primary PO creation orchestration failed: {exc}"
                return fallback_result
        return self._request("POST", "/purchase-orders", json=po_data)

    def post_invoice(self, invoice_data: dict[str, Any]) -> dict[str, Any]:
        if self._is_ais_context():
            return self._run_studio_orchestration(
                action_label="post_invoice",
                payload=invoice_data,
                preferred_names=["JDE_ORCH_04_Add_Supplier_Invoice"],
                keywords=["invoice", "voucher", "supplier invoice", "payable"],
            )
        return self._request("POST", "/ap/invoices/post", json=invoice_data)

    def create_journal_entry(self, entry_data: dict[str, Any]) -> dict[str, Any]:
        if self._is_ais_context():
            return self._run_studio_orchestration(
                action_label="create_journal_entry",
                payload=entry_data,
                preferred_names=[],
                keywords=["journal", "ledger", "gl entry", "general ledger", "unposted je"],
            )
        return self._request("POST", "/gl/journal-entries", json=entry_data)

    def get_cost_centers(self) -> list[dict[str, Any]]:
        return self._request("GET", "/cost-centers").get("items", [])

    def get_currencies(self) -> list[dict[str, Any]]:
        return self._request("GET", "/currencies").get("items", [])


class JDEDatabaseConnector(BaseJDEConnector):
    TABLE_MAP = {"vendors": "F0401", "ap_invoices": "F0411", "gl_accounts": "F1000", "customers": "F0101", "purchase_orders": "F4301"}

    def __init__(self) -> None:
        self.connection_string = settings.jde_database_url or ""

    def _connect(self):
        return pyodbc.connect(self.connection_string, timeout=settings.jde_db_query_timeout_seconds, autocommit=False)

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                cursor = connection.cursor()
                cursor.timeout = settings.jde_db_query_timeout_seconds
                cursor.execute(sql, params)
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as exc:
            logger.exception("JD Edwards database query failed.")
            raise JDEConnectorError(str(exc)) from exc

    def get_gl_accounts(self, company_id: str | None = None) -> list[dict[str, Any]]:
        return [JDEDataMapper.map_gl_account(row) for row in self._query(f"SELECT * FROM {self.TABLE_MAP['gl_accounts']}")]

    def get_ap_invoices(self, vendor_id: str | None = None, from_date: date | None = None, to_date: date | None = None) -> list[dict[str, Any]]:
        query = f"SELECT * FROM {self.TABLE_MAP['ap_invoices']} WHERE 1=1"
        params: list[Any] = []
        if vendor_id:
            query += " AND AN8 = ?"
            params.append(vendor_id)
        return [JDEDataMapper.map_invoice(row) for row in self._query(query, tuple(params))]

    def get_vendors(self, search_term: str | None = None) -> list[dict[str, Any]]:
        return [JDEDataMapper.map_vendor(row) for row in self._query(f"SELECT * FROM {self.TABLE_MAP['vendors']}")]

    def get_customers(self, search_term: str | None = None) -> list[dict[str, Any]]:
        return self._query(f"SELECT * FROM {self.TABLE_MAP['customers']}")

    def get_purchase_orders(self, po_number: str | None = None) -> list[dict[str, Any]]:
        return self._query(f"SELECT * FROM {self.TABLE_MAP['purchase_orders']}")

    def create_po(self, po_data: dict[str, Any]) -> dict[str, Any]:
        raise JDEConnectorError("Database connector is read-only for safety.")

    def post_invoice(self, invoice_data: dict[str, Any]) -> dict[str, Any]:
        raise JDEConnectorError("Database connector is read-only for safety.")

    def create_journal_entry(self, entry_data: dict[str, Any]) -> dict[str, Any]:
        raise JDEConnectorError("Database connector is read-only for safety.")

    def get_cost_centers(self) -> list[dict[str, Any]]:
        return []

    def get_currencies(self) -> list[dict[str, Any]]:
        return [{"code": "USD"}, {"code": "EUR"}]


class JDEConnectorFactory:
    @staticmethod
    def create() -> BaseJDEConnector:
        if settings.jde_connection_mode == "api":
            return JDERestConnector()
        if settings.jde_connection_mode == "database":
            return JDEDatabaseConnector()
        return JDERestConnector()
