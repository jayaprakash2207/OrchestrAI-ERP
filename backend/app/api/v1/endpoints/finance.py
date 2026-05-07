from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.exceptions import AppError, ResourceNotFoundError
from app.db.session import get_db
from app.models.enums import APInvoiceStatus, AccountType, ApprovalStatus, AuditAction, JournalEntryStatus
from app.models.financial import APInvoice, APInvoiceApproval, APInvoiceLineItem, ARInvoice, AuditLog, CostCenter, Customer, GLAccount, JournalEntry, Vendor
from app.schemas.common import PaginatedResponse
from app.schemas.financial import (
    APAgingDetail,
    APAgingResponse,
    ARAgingDetail,
    ARAgingResponse,
    APInvoiceApproveRequest,
    APInvoiceCreate,
    APInvoiceDetailResponse,
    APInvoiceLineItemResponse,
    APInvoicePaymentRequest,
    APInvoiceResponse,
    APInvoiceVoidRequest,
    ApprovalHistoryResponse,
    BalanceSheetResponse,
    FinancialStatementAccountLine,
    FinancialStatementSection,
    GLDetailResponse,
    GLAccountCreate,
    GLAccountDetailResponse,
    GLAccountResponse,
    GLAccountSummary,
    GLAccountUpdate,
    IncomeStatementResponse,
    JournalBatchDetailResponse,
    JournalBatchValidationResponse,
    JournalEntryCreateRequest,
    JournalEntrySummary,
    TrialBalanceAccountLine,
    TrialBalanceResponse,
    VendorSummary,
)
from app.services.audit import create_audit_entry

router = APIRouter(prefix="/finance", tags=["finance"])
_REPORT_CACHE: dict[str, tuple[datetime, dict | str]] = {}


def _serialize_model(instance) -> dict:
    data: dict = {}
    for column in instance.__table__.columns:
        value = getattr(instance, column.name)
        data[column.name] = str(value) if isinstance(value, (UUID, Decimal, date)) else value
    return data


def _cache_key(prefix: str, **params) -> str:
    return f"{prefix}:{'|'.join(f'{key}={params[key]}' for key in sorted(params))}"


def _cache_get(key: str, ttl_seconds: int = 60):
    cached = _REPORT_CACHE.get(key)
    if not cached:
        return None
    stored_at, payload = cached
    if (datetime.utcnow() - stored_at).total_seconds() > ttl_seconds:
        _REPORT_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: dict | str) -> None:
    _REPORT_CACHE[key] = (datetime.utcnow(), payload)


def _audit_report_access(db: Session, request: Request, report_name: str, filters: dict) -> None:
    create_audit_entry(
        db,
        table_name="reports",
        record_id=UUID("00000000-0000-0000-0000-000000000000"),
        action=AuditAction.CREATE,
        request=request,
        after_values={"report": report_name, "filters": filters},
    )


def _export_response(payload: dict, export: str) -> Response | dict:
    if export == "csv":
        rows = []
        if "accounts" in payload:
            lines = payload["accounts"]
        elif "details" in payload:
            lines = payload["details"]
        elif "transactions" in payload:
            lines = payload["transactions"]
        else:
            lines = []
        if lines:
            headers = list(lines[0].keys())
            rows.append(",".join(headers))
            for line in lines:
                rows.append(",".join(str(line.get(header, "")) for header in headers))
        else:
            rows.append("message")
            rows.append("no_data")
        return Response("\n".join(rows), media_type="text/csv")
    return payload


def _account_or_404(db: Session, account_id: UUID) -> GLAccount:
    account = db.scalar(
        select(GLAccount)
        .options(selectinload(GLAccount.parent_account), selectinload(GLAccount.child_accounts), selectinload(GLAccount.cost_center))
        .where(GLAccount.id == account_id)
    )
    if not account:
        raise ResourceNotFoundError("GL account not found.")
    return account


def _invoice_or_404(db: Session, invoice_id: UUID) -> APInvoice:
    invoice = db.scalar(
        select(APInvoice)
        .options(
            selectinload(APInvoice.vendor),
            selectinload(APInvoice.line_items).selectinload(APInvoiceLineItem.gl_account),
            selectinload(APInvoice.approvals),
        )
        .where(APInvoice.id == invoice_id)
    )
    if not invoice:
        raise ResourceNotFoundError("AP invoice not found.")
    return invoice


def _validate_cost_center(db: Session, cost_center_id: UUID | None) -> None:
    if cost_center_id and not db.scalar(select(CostCenter.id).where(CostCenter.id == cost_center_id)):
        raise AppError("Cost center does not exist.", error_code="invalid_cost_center", status_code=400)


def _validate_parent_account(db: Session, parent_account_id: UUID | None, account_id: UUID | None = None) -> GLAccount | None:
    if not parent_account_id:
        return None
    parent = db.scalar(select(GLAccount).where(GLAccount.id == parent_account_id))
    if not parent:
        raise AppError("Parent account does not exist.", error_code="invalid_parent_account", status_code=400)
    if account_id and parent_account_id == account_id:
        raise AppError("An account cannot be its own parent.", error_code="invalid_parent_account", status_code=400)
    return parent


def _journal_history_for_account(db: Session, account_id: UUID, limit: int = 10) -> list[JournalEntry]:
    return list(
        db.scalars(
            select(JournalEntry)
            .where(JournalEntry.account_id == account_id)
            .order_by(JournalEntry.journal_date.desc(), JournalEntry.created_at.desc())
            .limit(limit)
        )
    )


def _resolve_finance_account(db: Session, *, account_number: str | None = None, account_type: AccountType | None = None, purpose: str) -> GLAccount:
    conditions = [GLAccount.is_active.is_(True)]
    if account_number:
        conditions.append(GLAccount.account_number == account_number)
    if account_type:
        conditions.append(GLAccount.account_type == account_type)
    account = db.scalar(select(GLAccount).where(and_(*conditions)).order_by(GLAccount.account_number.asc()))
    if not account:
        raise AppError(
            f"Required {purpose} account is not configured.",
            error_code="missing_finance_account",
            details={"purpose": purpose, "account_number": account_number, "account_type": account_type.value if account_type else None},
            status_code=400,
        )
    return account


def _gl_account_summary(account: GLAccount) -> GLAccountSummary:
    return GLAccountSummary.model_validate(account, from_attributes=True)


def _gl_account_detail(db: Session, account: GLAccount) -> GLAccountDetailResponse:
    transactions = [JournalEntrySummary.model_validate(txn, from_attributes=True) for txn in _journal_history_for_account(db, account.id)]
    payload = GLAccountResponse.model_validate(account, from_attributes=True).model_dump()
    payload["transactions"] = [txn.model_dump() for txn in transactions]
    return GLAccountDetailResponse.model_validate(payload)


def _invoice_response(invoice: APInvoice) -> APInvoiceResponse:
    line_items = [
        APInvoiceLineItemResponse.model_validate(
            {
                **APInvoiceLineItemResponse.model_validate(item, from_attributes=True).model_dump(),
                "gl_account": _gl_account_summary(item.gl_account) if item.gl_account else None,
            }
        )
        for item in invoice.line_items
    ]
    payload = APInvoiceResponse.model_validate(invoice, from_attributes=True).model_dump()
    payload["line_items"] = [item.model_dump() for item in line_items]
    payload["days_overdue"] = invoice.days_overdue
    return APInvoiceResponse.model_validate(payload)


def _invoice_detail_response(invoice: APInvoice) -> APInvoiceDetailResponse:
    base = _invoice_response(invoice).model_dump()
    base["vendor"] = VendorSummary.model_validate(invoice.vendor, from_attributes=True).model_dump()
    base["approval_history"] = [
        ApprovalHistoryResponse.model_validate(approval, from_attributes=True).model_dump() for approval in invoice.approvals
    ]
    return APInvoiceDetailResponse.model_validate(base)


def _create_journal_entry(
    db: Session,
    *,
    batch_id: str,
    journal_date: date,
    account_id: UUID,
    debit: Decimal,
    credit: Decimal,
    description: str,
    cost_center_id: UUID | None = None,
    currency: str = "USD",
    created_by: str | None = None,
) -> JournalEntry:
    entry = JournalEntry(
        journal_batch_id=batch_id,
        journal_date=journal_date,
        account_id=account_id,
        debit=debit,
        credit=credit,
        description=description,
        cost_center_id=cost_center_id,
        currency=currency,
        status=JournalEntryStatus.POSTED,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(entry)
    return entry


def _batch_entries(db: Session, batch_id: str) -> list[JournalEntry]:
    entries = list(
        db.scalars(
            select(JournalEntry)
            .options(selectinload(JournalEntry.account))
            .where(JournalEntry.journal_batch_id == batch_id)
            .order_by(JournalEntry.journal_date.asc(), JournalEntry.created_at.asc())
        )
    )
    if not entries:
        raise ResourceNotFoundError("Journal batch not found.")
    return entries


def _batch_totals(entries: list[JournalEntry]) -> tuple[Decimal, Decimal]:
    total_debit = sum((entry.debit for entry in entries), Decimal("0.00"))
    total_credit = sum((entry.credit for entry in entries), Decimal("0.00"))
    return total_debit, total_credit


def _batch_status(entries: list[JournalEntry]) -> str:
    statuses = {entry.status for entry in entries}
    if statuses == {JournalEntryStatus.REVERSED}:
        return "REVERSED"
    if statuses == {JournalEntryStatus.POSTED}:
        return "POSTED"
    return "DRAFT"


def _journal_entry_summary(entry: JournalEntry, running_balance: Decimal | None = None) -> JournalEntrySummary:
    payload = JournalEntrySummary.model_validate(entry, from_attributes=True).model_dump()
    payload["account_name"] = entry.account.account_name if entry.account else None
    payload["account_type"] = entry.account.account_type if entry.account else None
    payload["running_balance"] = running_balance
    return JournalEntrySummary.model_validate(payload)


@router.post("/gl-accounts", response_model=GLAccountResponse, status_code=status.HTTP_201_CREATED)
def create_gl_account(payload: GLAccountCreate, request: Request, db: Session = Depends(get_db)) -> GLAccountResponse:
    existing = db.scalar(select(GLAccount.id).where(GLAccount.account_number == payload.account_number.upper()))
    if existing:
        raise AppError("Account number must be unique.", error_code="duplicate_account_number", status_code=400)

    _validate_parent_account(db, payload.parent_account_id)
    _validate_cost_center(db, payload.cost_center_id)

    account = GLAccount(
        account_number=payload.account_number,
        account_name=payload.account_name,
        account_type=payload.account_type,
        parent_account_id=payload.parent_account_id,
        cost_center_id=payload.cost_center_id,
        is_active=payload.is_active,
        created_by=request.headers.get("X-User-ID"),
        updated_by=request.headers.get("X-User-ID"),
    )
    db.add(account)
    db.flush()
    create_audit_entry(
        db,
        table_name="gl_accounts",
        record_id=account.id,
        action=AuditAction.CREATE,
        request=request,
        after_values=_serialize_model(account),
    )
    db.commit()
    db.refresh(account)
    return GLAccountResponse.model_validate(account, from_attributes=True)


@router.get("/gl-accounts", response_model=PaginatedResponse[GLAccountSummary])
def list_gl_accounts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    account_type: AccountType | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
) -> PaginatedResponse[GLAccountSummary]:
    filters = []
    if account_type:
        filters.append(GLAccount.account_type == account_type)
    if is_active is not None:
        filters.append(GLAccount.is_active.is_(is_active))
    if search:
        search_value = f"%{search.strip()}%"
        filters.append(or_(GLAccount.account_number.ilike(search_value), GLAccount.account_name.ilike(search_value)))

    count_stmt = select(func.count()).select_from(GLAccount)
    data_stmt = select(GLAccount).order_by(GLAccount.account_number.asc()).offset(skip).limit(limit)
    if filters:
        count_stmt = count_stmt.where(*filters)
        data_stmt = data_stmt.where(*filters)

    total = db.scalar(count_stmt) or 0
    accounts = list(db.scalars(data_stmt))
    return PaginatedResponse[GLAccountSummary](
        total=total,
        page=(skip // limit) + 1 if limit else 1,
        page_size=limit,
        items=[GLAccountSummary.model_validate(account, from_attributes=True) for account in accounts],
    )


@router.get("/gl-accounts/{account_id}", response_model=GLAccountDetailResponse)
def get_gl_account(account_id: UUID, db: Session = Depends(get_db)) -> GLAccountDetailResponse:
    account = _account_or_404(db, account_id)
    return _gl_account_detail(db, account)


@router.put("/gl-accounts/{account_id}", response_model=GLAccountResponse)
def update_gl_account(
    account_id: UUID,
    payload: GLAccountUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> GLAccountResponse:
    account = _account_or_404(db, account_id)
    before = _serialize_model(account)

    if payload.parent_account_id:
        _validate_parent_account(db, payload.parent_account_id, account.id)
    _validate_cost_center(db, payload.cost_center_id)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(account, field, value)
    account.updated_by = request.headers.get("X-User-ID")

    db.add(account)
    db.flush()
    create_audit_entry(
        db,
        table_name="gl_accounts",
        record_id=account.id,
        action=AuditAction.UPDATE,
        request=request,
        before_values=before,
        after_values=_serialize_model(account),
    )
    db.commit()
    db.refresh(account)
    return GLAccountResponse.model_validate(account, from_attributes=True)


@router.delete("/gl-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gl_account(account_id: UUID, request: Request, db: Session = Depends(get_db)) -> Response:
    account = _account_or_404(db, account_id)
    before = _serialize_model(account)
    transaction_count = db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.account_id == account.id)) or 0

    if transaction_count > 0:
        account.is_active = False
        account.updated_by = request.headers.get("X-User-ID")
        create_audit_entry(
            db,
            table_name="gl_accounts",
            record_id=account.id,
            action=AuditAction.DELETE,
            request=request,
            before_values=before,
            after_values=_serialize_model(account),
        )
    else:
        create_audit_entry(
            db,
            table_name="gl_accounts",
            record_id=account.id,
            action=AuditAction.DELETE,
            request=request,
            before_values=before,
            after_values=None,
        )
        db.delete(account)

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/ap-invoices", response_model=APInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_ap_invoice(payload: APInvoiceCreate, request: Request, db: Session = Depends(get_db)) -> APInvoiceResponse:
    vendor = db.scalar(select(Vendor).where(Vendor.id == payload.vendor_id))
    if not vendor:
        raise AppError("Vendor does not exist.", error_code="invalid_vendor", status_code=400)

    duplicate = db.scalar(
        select(APInvoice.id).where(APInvoice.vendor_id == payload.vendor_id, APInvoice.invoice_number == payload.invoice_number)
    )
    if duplicate:
        raise AppError("Invoice number must be unique per vendor.", error_code="duplicate_invoice_number", status_code=400)

    invoice = APInvoice(
        invoice_number=payload.invoice_number,
        vendor_id=payload.vendor_id,
        amount=payload.amount,
        currency=payload.currency,
        invoice_date=payload.invoice_date,
        due_date=payload.due_date,
        status=APInvoiceStatus.DRAFT,
        approval_status=ApprovalStatus.PENDING,
        approval_level=1,
        created_by=request.headers.get("X-User-ID"),
        updated_by=request.headers.get("X-User-ID"),
    )
    for line in payload.line_items:
        invoice.line_items.append(
            APInvoiceLineItem(
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
                gl_account_id=line.gl_account_id,
                created_by=request.headers.get("X-User-ID"),
                updated_by=request.headers.get("X-User-ID"),
            )
        )

    db.add(invoice)
    db.flush()
    create_audit_entry(
        db,
        table_name="ap_invoices",
        record_id=invoice.id,
        action=AuditAction.CREATE,
        request=request,
        after_values=_serialize_model(invoice),
    )
    db.commit()
    invoice = _invoice_or_404(db, invoice.id)
    return _invoice_response(invoice)


@router.get("/ap-invoices", response_model=PaginatedResponse[APInvoiceResponse])
def list_ap_invoices(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    vendor_id: UUID | None = None,
    status_filter: APInvoiceStatus | None = Query(default=None, alias="status"),
    approval_status: ApprovalStatus | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    db: Session = Depends(get_db),
) -> PaginatedResponse[APInvoiceResponse]:
    filters = []
    if vendor_id:
        filters.append(APInvoice.vendor_id == vendor_id)
    if status_filter:
        filters.append(APInvoice.status == status_filter)
    if approval_status:
        filters.append(APInvoice.approval_status == approval_status)
    if from_date:
        filters.append(APInvoice.invoice_date >= from_date)
    if to_date:
        filters.append(APInvoice.invoice_date <= to_date)
    if amount_min is not None:
        filters.append(APInvoice.amount >= amount_min)
    if amount_max is not None:
        filters.append(APInvoice.amount <= amount_max)

    overdue_sort = case((and_(APInvoice.status != APInvoiceStatus.PAID, APInvoice.due_date < date.today()), 0), else_=1)
    stmt = select(APInvoice).options(selectinload(APInvoice.line_items)).order_by(overdue_sort, APInvoice.due_date.asc()).offset(skip).limit(limit)
    count_stmt = select(func.count()).select_from(APInvoice)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    invoices = list(db.scalars(stmt))
    total = db.scalar(count_stmt) or 0
    return PaginatedResponse[APInvoiceResponse](
        total=total,
        page=(skip // limit) + 1 if limit else 1,
        page_size=limit,
        items=[_invoice_response(invoice) for invoice in invoices],
    )


@router.get("/ap-invoices/{invoice_id}", response_model=APInvoiceDetailResponse)
def get_ap_invoice(invoice_id: UUID, db: Session = Depends(get_db)) -> APInvoiceDetailResponse:
    invoice = _invoice_or_404(db, invoice_id)
    return _invoice_detail_response(invoice)


@router.post("/ap-invoices/{invoice_id}/approve", response_model=APInvoiceDetailResponse)
def approve_ap_invoice(
    invoice_id: UUID,
    payload: APInvoiceApproveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> APInvoiceDetailResponse:
    invoice = _invoice_or_404(db, invoice_id)
    if invoice.status != APInvoiceStatus.DRAFT:
        raise AppError("Only draft invoices can be approved.", error_code="invalid_state_transition", status_code=400)
    if invoice.approval_status == ApprovalStatus.APPROVED:
        raise AppError("Invoice is already approved.", error_code="invalid_state_transition", status_code=400)

    required_level = 2 if invoice.amount > Decimal(str(settings.finance_ap_approval_threshold)) else 1
    next_level = len(invoice.approvals) + 1
    approval = APInvoiceApproval(
        invoice_id=invoice.id,
        approval_level=next_level,
        approved_by=request.headers.get("X-User-ID", "system"),
        notes=payload.notes,
        created_by=request.headers.get("X-User-ID"),
        updated_by=request.headers.get("X-User-ID"),
    )
    db.add(approval)

    invoice.approval_level = next_level
    invoice.approval_status = ApprovalStatus.APPROVED if next_level >= required_level else ApprovalStatus.PENDING
    invoice.updated_by = request.headers.get("X-User-ID")
    db.flush()
    create_audit_entry(
        db,
        table_name="ap_invoices",
        record_id=invoice.id,
        action=AuditAction.UPDATE,
        request=request,
        after_values={"event": "approve", "approval_level": invoice.approval_level, "approval_status": invoice.approval_status.value, "notes": payload.notes},
    )
    db.commit()
    invoice = _invoice_or_404(db, invoice.id)
    return _invoice_detail_response(invoice)


@router.post("/ap-invoices/{invoice_id}/post", response_model=APInvoiceDetailResponse)
def post_ap_invoice(invoice_id: UUID, request: Request, db: Session = Depends(get_db)) -> APInvoiceDetailResponse:
    invoice = _invoice_or_404(db, invoice_id)
    if invoice.status != APInvoiceStatus.DRAFT:
        raise AppError("Only draft invoices can be posted.", error_code="invalid_state_transition", status_code=400)
    if invoice.approval_status != ApprovalStatus.APPROVED:
        raise AppError("Invoice must be fully approved before posting.", error_code="invalid_state_transition", status_code=400)

    payable_account = _resolve_finance_account(
        db,
        account_number=settings.finance_ap_payable_account_number,
        account_type=AccountType.LIABILITY,
        purpose="AP payable",
    )
    posting_user = request.headers.get("X-User-ID")
    batch_id = f"AP-{invoice.invoice_number}-{uuid4().hex[:8]}"

    for item in invoice.line_items:
        line_account = db.get(GLAccount, item.gl_account_id) if item.gl_account_id else None
        if not line_account:
            line_account = _resolve_finance_account(db, account_type=AccountType.EXPENSE, purpose="expense")
        _create_journal_entry(
            db,
            batch_id=batch_id,
            journal_date=invoice.invoice_date,
            account_id=line_account.id,
            debit=item.amount,
            credit=Decimal("0.00"),
            description=f"AP invoice {invoice.invoice_number} line item",
            created_by=posting_user,
        )

    _create_journal_entry(
        db,
        batch_id=batch_id,
        journal_date=invoice.invoice_date,
        account_id=payable_account.id,
        debit=Decimal("0.00"),
        credit=invoice.amount,
        description=f"AP invoice {invoice.invoice_number} payable",
        created_by=posting_user,
    )

    invoice.status = APInvoiceStatus.POSTED
    invoice.updated_by = posting_user
    db.flush()
    create_audit_entry(
        db,
        table_name="ap_invoices",
        record_id=invoice.id,
        action=AuditAction.UPDATE,
        request=request,
        after_values={"event": "post", "journal_batch_id": batch_id, "status": invoice.status.value},
    )
    db.commit()
    invoice = _invoice_or_404(db, invoice.id)
    return _invoice_detail_response(invoice)


@router.post("/ap-invoices/{invoice_id}/pay", response_model=APInvoiceDetailResponse)
def pay_ap_invoice(
    invoice_id: UUID,
    payload: APInvoicePaymentRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> APInvoiceDetailResponse:
    invoice = _invoice_or_404(db, invoice_id)
    if invoice.status != APInvoiceStatus.POSTED:
        raise AppError("Only posted invoices can be paid.", error_code="invalid_state_transition", status_code=400)

    payable_account = _resolve_finance_account(
        db,
        account_number=settings.finance_ap_payable_account_number,
        account_type=AccountType.LIABILITY,
        purpose="AP payable",
    )
    cash_account = _resolve_finance_account(
        db,
        account_number=settings.finance_cash_account_number,
        account_type=AccountType.ASSET,
        purpose="cash",
    )
    batch_id = f"PAY-{invoice.invoice_number}-{uuid4().hex[:8]}"
    payment_user = request.headers.get("X-User-ID")

    _create_journal_entry(
        db,
        batch_id=batch_id,
        journal_date=payload.payment_date,
        account_id=payable_account.id,
        debit=invoice.amount,
        credit=Decimal("0.00"),
        description=f"AP payment for {invoice.invoice_number}",
        created_by=payment_user,
    )
    _create_journal_entry(
        db,
        batch_id=batch_id,
        journal_date=payload.payment_date,
        account_id=cash_account.id,
        debit=Decimal("0.00"),
        credit=invoice.amount,
        description=f"Cash disbursement for {invoice.invoice_number}",
        created_by=payment_user,
    )

    invoice.status = APInvoiceStatus.PAID
    invoice.payment_date = payload.payment_date
    invoice.payment_method = payload.payment_method
    invoice.updated_by = payment_user
    db.flush()
    create_audit_entry(
        db,
        table_name="ap_invoices",
        record_id=invoice.id,
        action=AuditAction.UPDATE,
        request=request,
        after_values={"event": "pay", "payment_method": payload.payment_method, "payment_date": payload.payment_date},
    )
    db.commit()
    invoice = _invoice_or_404(db, invoice.id)
    return _invoice_detail_response(invoice)


@router.post("/ap-invoices/{invoice_id}/void", response_model=APInvoiceDetailResponse)
def void_ap_invoice(
    invoice_id: UUID,
    payload: APInvoiceVoidRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> APInvoiceDetailResponse:
    invoice = _invoice_or_404(db, invoice_id)
    if invoice.status not in {APInvoiceStatus.DRAFT, APInvoiceStatus.POSTED}:
        raise AppError("Only draft or posted invoices can be voided.", error_code="invalid_state_transition", status_code=400)

    if invoice.status == APInvoiceStatus.POSTED:
        source_entries = list(
            db.scalars(
                select(JournalEntry).where(
                    JournalEntry.description.ilike(f"%{invoice.invoice_number}%"),
                    JournalEntry.status == JournalEntryStatus.POSTED,
                )
            )
        )
        reversal_batch_id = f"VOID-{invoice.invoice_number}-{uuid4().hex[:8]}"
        void_user = request.headers.get("X-User-ID")
        for entry in source_entries:
            _create_journal_entry(
                db,
                batch_id=reversal_batch_id,
                journal_date=date.today(),
                account_id=entry.account_id,
                debit=entry.credit,
                credit=entry.debit,
                description=f"Reversal for voided invoice {invoice.invoice_number}",
                cost_center_id=entry.cost_center_id,
                currency=entry.currency,
                created_by=void_user,
            )

    invoice.status = APInvoiceStatus.VOID
    invoice.updated_by = request.headers.get("X-User-ID")
    db.flush()
    create_audit_entry(
        db,
        table_name="ap_invoices",
        record_id=invoice.id,
        action=AuditAction.UPDATE,
        request=request,
        after_values={"event": "void", "reason": payload.reason, "status": invoice.status.value},
    )
    db.commit()
    invoice = _invoice_or_404(db, invoice.id)
    return _invoice_detail_response(invoice)


@router.post("/journal-entries", response_model=JournalEntrySummary, status_code=status.HTTP_201_CREATED)
def create_journal_entry_route(
    payload: JournalEntryCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> JournalEntrySummary:
    account = db.scalar(select(GLAccount).where(GLAccount.id == payload.account_id))
    if not account:
        raise AppError("Account does not exist.", error_code="invalid_account", status_code=400)
    _validate_cost_center(db, payload.cost_center_id)
    batch_id = payload.journal_batch_id or f"JB-{payload.journal_date:%Y%m%d}-{uuid4().hex[:8]}"
    entry = JournalEntry(
        journal_batch_id=batch_id,
        journal_date=payload.journal_date,
        account_id=payload.account_id,
        debit=payload.debit,
        credit=payload.credit,
        description=payload.description,
        cost_center_id=payload.cost_center_id,
        currency=payload.currency,
        status=JournalEntryStatus.DRAFT,
        created_by=request.headers.get("X-User-ID"),
        updated_by=request.headers.get("X-User-ID"),
    )
    db.add(entry)
    db.flush()
    create_audit_entry(
        db,
        table_name="journal_entries",
        record_id=entry.id,
        action=AuditAction.CREATE,
        request=request,
        after_values=_serialize_model(entry),
    )
    db.commit()
    entry = db.scalar(select(JournalEntry).options(selectinload(JournalEntry.account)).where(JournalEntry.id == entry.id))
    assert entry is not None
    return _journal_entry_summary(entry)


@router.get("/journal-entries", response_model=PaginatedResponse[JournalEntrySummary])
def list_journal_entries(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    journal_batch_id: str | None = None,
    account_id: UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    status_filter: JournalEntryStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> PaginatedResponse[JournalEntrySummary]:
    filters = []
    if journal_batch_id:
        filters.append(JournalEntry.journal_batch_id == journal_batch_id)
    if account_id:
        filters.append(JournalEntry.account_id == account_id)
    if from_date:
        filters.append(JournalEntry.journal_date >= from_date)
    if to_date:
        filters.append(JournalEntry.journal_date <= to_date)
    if status_filter:
        filters.append(JournalEntry.status == status_filter)

    stmt = (
        select(JournalEntry)
        .options(selectinload(JournalEntry.account))
        .order_by(JournalEntry.journal_date.asc(), JournalEntry.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    count_stmt = select(func.count()).select_from(JournalEntry)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    entries = list(db.scalars(stmt))
    total = db.scalar(count_stmt) or 0
    running_balance = Decimal("0.00")
    items: list[JournalEntrySummary] = []
    for entry in entries:
        running_balance += entry.debit - entry.credit
        items.append(_journal_entry_summary(entry, running_balance))
    return PaginatedResponse[JournalEntrySummary](
        total=total,
        page=(skip // limit) + 1,
        page_size=limit,
        items=items,
    )


@router.get("/journal-batches/{batch_id}", response_model=JournalBatchDetailResponse)
def get_journal_batch(batch_id: str, db: Session = Depends(get_db)) -> JournalBatchDetailResponse:
    entries = _batch_entries(db, batch_id)
    total_debit, total_credit = _batch_totals(entries)
    posting_information = None
    audit_log = db.scalar(
        select(AuditLog).where(AuditLog.table_name == "journal_batches", AuditLog.record_id == UUID("00000000-0000-0000-0000-000000000000")).order_by(AuditLog.timestamp.desc())
    )
    if audit_log and audit_log.after_values and audit_log.after_values.get("batch_id") == batch_id:
        posting_information = audit_log.after_values
    return JournalBatchDetailResponse(
        batch_id=batch_id,
        status=_batch_status(entries),
        total_debit=total_debit,
        total_credit=total_credit,
        is_balanced=total_debit == total_credit,
        posting_information=posting_information,
        entries=[_journal_entry_summary(entry) for entry in entries],
    )


@router.post("/journal-batches/{batch_id}/validate", response_model=JournalBatchValidationResponse)
def validate_journal_batch(batch_id: str, db: Session = Depends(get_db)) -> JournalBatchValidationResponse:
    entries = _batch_entries(db, batch_id)
    total_debit, total_credit = _batch_totals(entries)
    difference = total_debit - total_credit
    if difference != 0:
        raise AppError(
            "Journal batch is unbalanced.",
            error_code="unbalanced_batch",
            details={"total_debit": str(total_debit), "total_credit": str(total_credit), "difference": str(difference)},
            status_code=400,
        )
    return JournalBatchValidationResponse(
        batch_id=batch_id,
        total_debit=total_debit,
        total_credit=total_credit,
        difference=Decimal("0.00"),
        is_balanced=True,
        message="Journal batch is balanced.",
    )


@router.post("/journal-batches/{batch_id}/post", response_model=JournalBatchDetailResponse)
def post_journal_batch(batch_id: str, request: Request, db: Session = Depends(get_db)) -> JournalBatchDetailResponse:
    entries = _batch_entries(db, batch_id)
    total_debit, total_credit = _batch_totals(entries)
    if total_debit != total_credit:
        raise AppError("Journal batch is unbalanced.", error_code="unbalanced_batch", status_code=400)
    if any(entry.status != JournalEntryStatus.DRAFT for entry in entries):
        raise AppError("All batch entries must be draft before posting.", error_code="invalid_state_transition", status_code=400)

    user_id = request.headers.get("X-User-ID")
    for entry in entries:
        entry.status = JournalEntryStatus.POSTED
        entry.updated_by = user_id
        account = entry.account
        account.balance += entry.debit - entry.credit
        account.ytd_debit += entry.debit
        account.ytd_credit += entry.credit
        account.updated_by = user_id

    create_audit_entry(
        db,
        table_name="journal_batches",
        record_id=UUID("00000000-0000-0000-0000-000000000000"),
        action=AuditAction.UPDATE,
        request=request,
        after_values={"batch_id": batch_id, "status": "POSTED", "posted_at": datetime.utcnow().isoformat()},
    )
    db.commit()
    return get_journal_batch(batch_id, db)


@router.post("/journal-batches/{batch_id}/reverse", response_model=JournalBatchDetailResponse)
def reverse_journal_batch(batch_id: str, request: Request, db: Session = Depends(get_db)) -> JournalBatchDetailResponse:
    entries = _batch_entries(db, batch_id)
    if any(entry.status != JournalEntryStatus.POSTED for entry in entries):
        raise AppError("Only posted batches can be reversed.", error_code="invalid_state_transition", status_code=400)

    reversal_batch_id = f"REV-{batch_id}-{uuid4().hex[:6]}"
    user_id = request.headers.get("X-User-ID")
    for entry in entries:
        account = entry.account
        _create_journal_entry(
            db,
            batch_id=reversal_batch_id,
            journal_date=date.today(),
            account_id=entry.account_id,
            debit=entry.credit,
            credit=entry.debit,
            description=f"Reversal of batch {batch_id}",
            cost_center_id=entry.cost_center_id,
            currency=entry.currency,
            created_by=user_id,
        )
        account.balance -= entry.debit - entry.credit
        account.ytd_debit -= entry.debit
        account.ytd_credit -= entry.credit
        account.updated_by = user_id
        entry.status = JournalEntryStatus.REVERSED
        entry.updated_by = user_id

    create_audit_entry(
        db,
        table_name="journal_batches",
        record_id=UUID("00000000-0000-0000-0000-000000000000"),
        action=AuditAction.UPDATE,
        request=request,
        after_values={"batch_id": batch_id, "status": "REVERSED", "reversal_batch_id": reversal_batch_id},
    )
    db.commit()
    return get_journal_batch(batch_id, db)


@router.get("/reports/trial-balance", response_model=TrialBalanceResponse)
def get_trial_balance(
    request: Request,
    as_of_date: date,
    include_zero_balance: bool = False,
    export: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    cache_key = _cache_key("trial_balance", as_of_date=str(as_of_date), include_zero_balance=include_zero_balance, export=export)
    cached = _cache_get(cache_key)
    if cached:
        return _export_response(cached, export)

    accounts = list(db.scalars(select(GLAccount).order_by(GLAccount.account_number.asc())))
    lines: list[dict] = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for account in accounts:
        debit_sum = db.scalar(select(func.coalesce(func.sum(JournalEntry.debit), 0)).where(JournalEntry.account_id == account.id, JournalEntry.journal_date <= as_of_date, JournalEntry.status != JournalEntryStatus.DRAFT)) or Decimal("0.00")
        credit_sum = db.scalar(select(func.coalesce(func.sum(JournalEntry.credit), 0)).where(JournalEntry.account_id == account.id, JournalEntry.journal_date <= as_of_date, JournalEntry.status != JournalEntryStatus.DRAFT)) or Decimal("0.00")
        debit_balance = Decimal(str(debit_sum))
        credit_balance = Decimal(str(credit_sum))
        if not include_zero_balance and debit_balance == 0 and credit_balance == 0:
            continue
        total_debit += debit_balance
        total_credit += credit_balance
        lines.append(TrialBalanceAccountLine(account_id=account.id, account_number=account.account_number, account_name=account.account_name, account_type=account.account_type, debit_balance=debit_balance, credit_balance=credit_balance).model_dump())

    payload = TrialBalanceResponse(as_of_date=as_of_date, total_debit=total_debit, total_credit=total_credit, is_balanced=total_debit == total_credit, accounts=[TrialBalanceAccountLine.model_validate(line) for line in lines]).model_dump(mode="json")
    _audit_report_access(db, request, "trial_balance", {"as_of_date": str(as_of_date), "include_zero_balance": include_zero_balance})
    db.commit()
    _cache_set(cache_key, payload)
    return _export_response(payload, export)


def _statement_section(accounts: list[GLAccount], as_of_date: date, db: Session, by_cost_center: bool = False) -> FinancialStatementSection:
    lines: list[FinancialStatementAccountLine] = []
    cost_center_totals: dict[str, Decimal] = {}
    total = Decimal("0.00")
    current = Decimal("0.00")
    for account in accounts:
        debit_sum = Decimal(str(db.scalar(select(func.coalesce(func.sum(JournalEntry.debit), 0)).where(JournalEntry.account_id == account.id, JournalEntry.journal_date <= as_of_date, JournalEntry.status != JournalEntryStatus.DRAFT)) or 0))
        credit_sum = Decimal(str(db.scalar(select(func.coalesce(func.sum(JournalEntry.credit), 0)).where(JournalEntry.account_id == account.id, JournalEntry.journal_date <= as_of_date, JournalEntry.status != JournalEntryStatus.DRAFT)) or 0))
        amount = debit_sum - credit_sum if account.account_type in {AccountType.ASSET, AccountType.EXPENSE} else credit_sum - debit_sum
        total += amount
        if account.account_number.startswith(("1", "2")):
            current += amount
        cost_center_code = account.cost_center.code if account.cost_center else None
        if by_cost_center and cost_center_code:
            cost_center_totals[cost_center_code] = cost_center_totals.get(cost_center_code, Decimal("0.00")) + amount
        lines.append(FinancialStatementAccountLine(account_id=account.id, account_number=account.account_number, account_name=account.account_name, amount=amount, cost_center_code=cost_center_code))
    return FinancialStatementSection(
        total=total,
        current=current,
        accounts=lines,
        cost_centers=[{"code": code, "amount": amount} for code, amount in sorted(cost_center_totals.items())] if by_cost_center else None,
    )


@router.get("/reports/balance-sheet", response_model=BalanceSheetResponse)
def get_balance_sheet(
    request: Request,
    as_of_date: date,
    by_cost_center: bool = False,
    export: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    cache_key = _cache_key("balance_sheet", as_of_date=str(as_of_date), by_cost_center=by_cost_center, export=export)
    cached = _cache_get(cache_key)
    if cached:
        return _export_response(cached, export)
    assets = _statement_section(list(db.scalars(select(GLAccount).options(selectinload(GLAccount.cost_center)).where(GLAccount.account_type == AccountType.ASSET).order_by(GLAccount.account_number.asc()))), as_of_date, db, by_cost_center)
    liabilities = _statement_section(list(db.scalars(select(GLAccount).options(selectinload(GLAccount.cost_center)).where(GLAccount.account_type == AccountType.LIABILITY).order_by(GLAccount.account_number.asc()))), as_of_date, db, by_cost_center)
    equity = _statement_section(list(db.scalars(select(GLAccount).options(selectinload(GLAccount.cost_center)).where(GLAccount.account_type == AccountType.EQUITY).order_by(GLAccount.account_number.asc()))), as_of_date, db, by_cost_center)
    payload = BalanceSheetResponse(as_of_date=as_of_date, assets=assets, liabilities=liabilities, equity=equity, total_liabilities_and_equity=liabilities.total + equity.total).model_dump(mode="json")
    _audit_report_access(db, request, "balance_sheet", {"as_of_date": str(as_of_date), "by_cost_center": by_cost_center})
    db.commit()
    _cache_set(cache_key, payload)
    return _export_response(payload, export)


@router.get("/reports/income-statement", response_model=IncomeStatementResponse)
def get_income_statement(
    request: Request,
    from_date: date,
    to_date: date,
    by_cost_center: bool = False,
    export: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    cache_key = _cache_key("income_statement", from_date=str(from_date), to_date=str(to_date), by_cost_center=by_cost_center, export=export)
    cached = _cache_get(cache_key)
    if cached:
        return _export_response(cached, export)

    def period_section(account_type: AccountType) -> FinancialStatementSection:
        accounts = list(db.scalars(select(GLAccount).options(selectinload(GLAccount.cost_center)).where(GLAccount.account_type == account_type).order_by(GLAccount.account_number.asc())))
        lines: list[FinancialStatementAccountLine] = []
        total = Decimal("0.00")
        cost_center_totals: dict[str, Decimal] = {}
        for account in accounts:
            debit_sum = Decimal(str(db.scalar(select(func.coalesce(func.sum(JournalEntry.debit), 0)).where(JournalEntry.account_id == account.id, JournalEntry.journal_date >= from_date, JournalEntry.journal_date <= to_date, JournalEntry.status != JournalEntryStatus.DRAFT)) or 0))
            credit_sum = Decimal(str(db.scalar(select(func.coalesce(func.sum(JournalEntry.credit), 0)).where(JournalEntry.account_id == account.id, JournalEntry.journal_date >= from_date, JournalEntry.journal_date <= to_date, JournalEntry.status != JournalEntryStatus.DRAFT)) or 0))
            amount = credit_sum - debit_sum if account_type == AccountType.REVENUE else debit_sum - credit_sum
            total += amount
            cc = account.cost_center.code if account.cost_center else None
            if by_cost_center and cc:
                cost_center_totals[cc] = cost_center_totals.get(cc, Decimal("0.00")) + amount
            lines.append(FinancialStatementAccountLine(account_id=account.id, account_number=account.account_number, account_name=account.account_name, amount=amount, cost_center_code=cc))
        return FinancialStatementSection(total=total, accounts=lines, cost_centers=[{"code": code, "amount": amount} for code, amount in sorted(cost_center_totals.items())] if by_cost_center else None)

    revenue = period_section(AccountType.REVENUE)
    expenses = period_section(AccountType.EXPENSE)
    operating_income = revenue.total - expenses.total
    payload = IncomeStatementResponse(period={"from_date": from_date, "to_date": to_date}, revenue=revenue, expenses=expenses, operating_income=operating_income, other_income=Decimal("0.00"), other_expense=Decimal("0.00"), net_income=operating_income).model_dump(mode="json")
    _audit_report_access(db, request, "income_statement", {"from_date": str(from_date), "to_date": str(to_date), "by_cost_center": by_cost_center})
    db.commit()
    _cache_set(cache_key, payload)
    return _export_response(payload, export)


def _aging_buckets_from_details(details: list[dict]) -> list[dict]:
    buckets = {"0-30": Decimal("0.00"), "31-60": Decimal("0.00"), "61-90": Decimal("0.00"), "90+": Decimal("0.00")}
    counts = {key: 0 for key in buckets}
    total = sum((Decimal(str(detail["amount"])) for detail in details), Decimal("0.00"))
    for detail in details:
        days = detail["days_overdue"]
        key = "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
        buckets[key] += Decimal(str(detail["amount"]))
        counts[key] += 1
    return [{"days_overdue": key, "count": counts[key], "amount": buckets[key], "percent": (buckets[key] / total * 100 if total else Decimal("0.00"))} for key in buckets]


@router.get("/reports/ap-aging", response_model=APAgingResponse)
def get_ap_aging(
    request: Request,
    as_of_date: date,
    by_vendor: bool = False,
    by_currency: bool = False,
    export: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    cache_key = _cache_key("ap_aging", as_of_date=str(as_of_date), by_vendor=by_vendor, by_currency=by_currency, export=export)
    cached = _cache_get(cache_key)
    if cached:
        return _export_response(cached, export)
    invoices = list(db.scalars(select(APInvoice).options(selectinload(APInvoice.vendor)).where(APInvoice.status.in_([APInvoiceStatus.DRAFT, APInvoiceStatus.POSTED]), APInvoice.due_date <= as_of_date)))
    details = sorted([
        APAgingDetail(invoice_number=invoice.invoice_number, vendor=invoice.vendor.vendor_name, amount=invoice.amount, due_date=invoice.due_date, days_overdue=max((as_of_date - invoice.due_date).days, 0), currency=invoice.currency).model_dump()
        for invoice in invoices
    ], key=lambda item: item["days_overdue"], reverse=True)
    payload = APAgingResponse(as_of_date=as_of_date, total_ap=sum((invoice.amount for invoice in invoices), Decimal("0.00")), aging_buckets=_aging_buckets_from_details(details), details=[APAgingDetail.model_validate(detail) for detail in details]).model_dump(mode="json")
    _audit_report_access(db, request, "ap_aging", {"as_of_date": str(as_of_date), "by_vendor": by_vendor, "by_currency": by_currency})
    db.commit()
    _cache_set(cache_key, payload)
    return _export_response(payload, export)


@router.get("/reports/ar-aging", response_model=ARAgingResponse)
def get_ar_aging(
    request: Request,
    as_of_date: date,
    by_customer: bool = False,
    by_currency: bool = False,
    export: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    cache_key = _cache_key("ar_aging", as_of_date=str(as_of_date), by_customer=by_customer, by_currency=by_currency, export=export)
    cached = _cache_get(cache_key)
    if cached:
        return _export_response(cached, export)
    invoices = list(db.scalars(select(ARInvoice).options(selectinload(ARInvoice.customer)).where(ARInvoice.status.in_([APInvoiceStatus.POSTED, APInvoiceStatus.DRAFT]), ARInvoice.due_date <= as_of_date)))
    details = sorted([
        ARAgingDetail(invoice_number=invoice.invoice_number, customer=invoice.customer.customer_name, amount=invoice.amount, due_date=invoice.due_date, days_overdue=max((as_of_date - invoice.due_date).days, 0), currency=invoice.currency).model_dump()
        for invoice in invoices
    ], key=lambda item: item["days_overdue"], reverse=True)
    payload = ARAgingResponse(as_of_date=as_of_date, total_ar=sum((invoice.amount for invoice in invoices), Decimal("0.00")), aging_buckets=_aging_buckets_from_details(details), details=[ARAgingDetail.model_validate(detail) for detail in details]).model_dump(mode="json")
    _audit_report_access(db, request, "ar_aging", {"as_of_date": str(as_of_date), "by_customer": by_customer, "by_currency": by_currency})
    db.commit()
    _cache_set(cache_key, payload)
    return _export_response(payload, export)


@router.get("/reports/gl-detail", response_model=GLDetailResponse)
def get_gl_detail_report(
    request: Request,
    account_id: UUID,
    from_date: date,
    to_date: date,
    export: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    cache_key = _cache_key("gl_detail", account_id=str(account_id), from_date=str(from_date), to_date=str(to_date), export=export)
    cached = _cache_get(cache_key)
    if cached:
        return _export_response(cached, export)
    account = _account_or_404(db, account_id)
    entries = list(db.scalars(select(JournalEntry).options(selectinload(JournalEntry.account)).where(JournalEntry.account_id == account_id, JournalEntry.journal_date >= from_date, JournalEntry.journal_date <= to_date).order_by(JournalEntry.journal_date.asc(), JournalEntry.created_at.asc())))
    running = Decimal("0.00")
    transactions = []
    for entry in entries:
        running += entry.debit - entry.credit
        transactions.append(_journal_entry_summary(entry, running).model_dump())
    payload = GLDetailResponse(account=_gl_account_summary(account), from_date=from_date, to_date=to_date, transactions=[JournalEntrySummary.model_validate(item) for item in transactions]).model_dump(mode="json")
    _audit_report_access(db, request, "gl_detail", {"account_id": str(account_id), "from_date": str(from_date), "to_date": str(to_date)})
    db.commit()
    _cache_set(cache_key, payload)
    return _export_response(payload, export)
