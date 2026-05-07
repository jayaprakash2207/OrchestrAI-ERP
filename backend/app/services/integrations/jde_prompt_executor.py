from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.integrations.jde_connector import BaseJDEConnector, JDEConnectorError, JDEConnectorFactory


class JDEPromptExecutionError(Exception):
    pass


@dataclass
class JDEExecutionPlan:
    action_type: str
    module: str
    summary: str
    parsed_payload: dict[str, Any]
    requires_confirmation: bool = True


class JDEPromptExecutor:
    def __init__(self, connector: BaseJDEConnector | None = None) -> None:
        self.connector = connector or JDEConnectorFactory.create()

    def plan(self, message: str, requested_module: str | None = None) -> JDEExecutionPlan:
        lowered = message.lower()
        if "purchase order" in lowered or re.search(r"\bcreate\s+(?:a\s+)?po\b", lowered):
            return self._plan_purchase_order(message)
        if "journal entry" in lowered or (("dr " in lowered or "debit" in lowered) and ("cr " in lowered or "credit" in lowered)):
            return self._plan_journal_entry(message)
        if "post invoice" in lowered or "post vendor invoice" in lowered:
            return self._plan_post_invoice(message)
        module = requested_module or "finance"
        raise JDEPromptExecutionError(
            f"Unsupported execution request for module '{module}'. Supported actions: create purchase order, post invoice, create journal entry."
        )

    def execute(self, plan: JDEExecutionPlan) -> dict[str, Any]:
        try:
            if plan.action_type == "create_po":
                return self.connector.create_po(plan.parsed_payload)
            if plan.action_type == "post_invoice":
                return self.connector.post_invoice(plan.parsed_payload)
            if plan.action_type == "create_journal_entry":
                return self.connector.create_journal_entry(plan.parsed_payload)
        except JDEConnectorError as exc:
            raise JDEPromptExecutionError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise JDEPromptExecutionError(f"JD Edwards execution failed: {exc}") from exc
        raise JDEPromptExecutionError(f"Unsupported action type: {plan.action_type}")

    def _plan_purchase_order(self, message: str) -> JDEExecutionPlan:
        quantity_match = re.search(r"for\s+(\d+)\s+units?", message, re.IGNORECASE)
        item_match = re.search(r"units?\s+of\s+([A-Za-z0-9\-_ ]+?)\s+from\s+(?:vendor\s+)?([A-Za-z0-9\-_ ]+)", message, re.IGNORECASE)
        vendor_match = re.search(r"from\s+(?:vendor\s+)?([A-Za-z0-9\-_ ]+)", message, re.IGNORECASE)
        if not quantity_match or not vendor_match:
            raise JDEPromptExecutionError("Could not parse purchase order request. Example: Create PO for 100 units of SKU-123 from Vendor ABC")
        quantity = int(quantity_match.group(1))
        item = item_match.group(1).strip() if item_match else "UNSPECIFIED_ITEM"
        vendor_name = vendor_match.group(1).strip()
        payload = {
            "vendor_name": vendor_name,
            "status": "OPEN",
            "line_items": [
                {
                    "item_code": item,
                    "description": item,
                    "quantity": quantity,
                }
            ],
        }
        return JDEExecutionPlan(
            action_type="create_po",
            module="supply_chain",
            summary=f"Create JD Edwards purchase order for {quantity} units of {item} from vendor {vendor_name}.",
            parsed_payload=payload,
        )

    def _plan_post_invoice(self, message: str) -> JDEExecutionPlan:
        invoice_match = re.search(r"invoice\s+([A-Za-z0-9\-_\/]+)", message, re.IGNORECASE)
        if not invoice_match:
            raise JDEPromptExecutionError("Could not parse invoice number. Example: Post invoice INV-001")
        invoice_number = invoice_match.group(1).strip()
        payload = {"invoice_number": invoice_number}
        return JDEExecutionPlan(
            action_type="post_invoice",
            module="finance",
            summary=f"Post JD Edwards invoice {invoice_number}.",
            parsed_payload=payload,
        )

    def _plan_journal_entry(self, message: str) -> JDEExecutionPlan:
        account_amount_pairs = re.findall(
            r"(?:dr|debit|cr|credit)\s+([A-Za-z0-9\-_]+)\s+\$?([0-9]+(?:\.[0-9]{1,2})?)",
            message,
            re.IGNORECASE,
        )
        if len(account_amount_pairs) < 2:
            raise JDEPromptExecutionError(
                "Could not parse journal entry. Example: Create journal entry DR 1200 5000 CR 1100 5000"
            )
        debit_match = re.search(r"(?:dr|debit)\s+([A-Za-z0-9\-_]+)\s+\$?([0-9]+(?:\.[0-9]{1,2})?)", message, re.IGNORECASE)
        credit_match = re.search(r"(?:cr|credit)\s+([A-Za-z0-9\-_]+)\s+\$?([0-9]+(?:\.[0-9]{1,2})?)", message, re.IGNORECASE)
        if not debit_match or not credit_match:
            raise JDEPromptExecutionError(
                "Journal entry must include one debit and one credit. Example: DR 1200 5000 CR 1100 5000"
            )
        debit_amount = float(debit_match.group(2))
        credit_amount = float(credit_match.group(2))
        if round(debit_amount, 2) != round(credit_amount, 2):
            raise JDEPromptExecutionError("Journal entry is not balanced. Debit and credit amounts must match.")
        payload = {
            "journal_batch_id": "AI-COPILOT",
            "entries": [
                {"account_number": debit_match.group(1), "debit": debit_amount, "credit": 0},
                {"account_number": credit_match.group(1), "debit": 0, "credit": credit_amount},
            ],
        }
        return JDEExecutionPlan(
            action_type="create_journal_entry",
            module="finance",
            summary=f"Create balanced JD Edwards journal entry for {debit_amount:.2f}.",
            parsed_payload=payload,
        )
