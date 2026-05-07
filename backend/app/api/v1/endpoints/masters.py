from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError, ResourceNotFoundError
from app.db.session import get_db
from app.models.enums import APInvoiceStatus, AuditAction
from app.models.financial import APInvoice, CostCenter, Customer, JournalEntry, PurchaseOrder, Vendor
from app.schemas.common import PaginatedResponse
from app.schemas.financial import CostCenterResponse, CustomerCreate, CustomerResponse, VendorCreate, VendorResponse
from app.services.audit import create_audit_entry

router = APIRouter(tags=["masters"])


def _serialize(instance) -> dict:
    return {column.name: str(getattr(instance, column.name)) for column in instance.__table__.columns}


def _vendor_response(db: Session, vendor: Vendor) -> VendorResponse:
    open_pos = db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.vendor_id == vendor.id)) or 0
    overdue = db.scalar(select(func.count()).select_from(APInvoice).where(APInvoice.vendor_id == vendor.id, APInvoice.status != APInvoiceStatus.PAID, APInvoice.due_date < func.current_date())) or 0
    payload = VendorResponse.model_validate(vendor, from_attributes=True).model_dump()
    payload["total_spending"] = vendor.total_spending
    payload["address"] = f"{payload.get('address', '')} | open_pos={open_pos} overdue_invoices={overdue}"
    return VendorResponse.model_validate(payload)


def _customer_response(db: Session, customer: Customer) -> CustomerResponse:
    credit_used = Decimal("0.00")
    if customer.ar_invoices:
        credit_used = sum((invoice.amount for invoice in customer.ar_invoices if invoice.status != APInvoiceStatus.PAID), Decimal("0.00"))
    payload = CustomerResponse.model_validate(customer, from_attributes=True).model_dump()
    payload["shipping_address"] = f"{payload.get('shipping_address') or ''} | credit_used={credit_used}"
    return CustomerResponse.model_validate(payload)


@router.get("/masters/vendors", response_model=PaginatedResponse[VendorResponse])
def list_vendors(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    search: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
) -> PaginatedResponse[VendorResponse]:
    filters = []
    if search:
        value = f"%{search}%"
        filters.append(or_(Vendor.vendor_number.ilike(value), Vendor.vendor_name.ilike(value)))
    if is_active is not None:
        filters.append(Vendor.is_active.is_(is_active))
    stmt = select(Vendor).options(selectinload(Vendor.invoices)).order_by(Vendor.vendor_number.asc()).offset(skip).limit(limit)
    count_stmt = select(func.count()).select_from(Vendor)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
    vendors = list(db.scalars(stmt))
    return PaginatedResponse[VendorResponse](
        total=db.scalar(count_stmt) or 0,
        page=(skip // limit) + 1,
        page_size=limit,
        items=[_vendor_response(db, vendor) for vendor in vendors],
    )


@router.post("/masters/vendors", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
def create_vendor(payload: VendorCreate, request: Request, db: Session = Depends(get_db)) -> VendorResponse:
    if db.scalar(select(Vendor.id).where(Vendor.vendor_number == payload.vendor_number)):
        raise AppError("Vendor number must be unique.", error_code="duplicate_vendor_number", status_code=400)
    vendor = Vendor(**payload.model_dump(), is_active=True, created_by=request.headers.get("X-User-ID"), updated_by=request.headers.get("X-User-ID"))
    db.add(vendor)
    db.flush()
    create_audit_entry(db, table_name="vendors", record_id=vendor.id, action=AuditAction.CREATE, request=request, after_values=_serialize(vendor))
    db.commit()
    db.refresh(vendor)
    return _vendor_response(db, vendor)


@router.get("/masters/vendors/{vendor_id}", response_model=VendorResponse)
def get_vendor(vendor_id: UUID, db: Session = Depends(get_db)) -> VendorResponse:
    vendor = db.scalar(select(Vendor).options(selectinload(Vendor.invoices)).where(Vendor.id == vendor_id))
    if not vendor:
        raise ResourceNotFoundError("Vendor not found.")
    return _vendor_response(db, vendor)


@router.get("/masters/customers", response_model=PaginatedResponse[CustomerResponse])
def list_customers(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    search: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
) -> PaginatedResponse[CustomerResponse]:
    filters = []
    if search:
        value = f"%{search}%"
        filters.append(or_(Customer.customer_number.ilike(value), Customer.customer_name.ilike(value)))
    if is_active is not None:
        filters.append(Customer.is_active.is_(is_active))
    stmt = select(Customer).options(selectinload(Customer.ar_invoices)).order_by(Customer.customer_number.asc()).offset(skip).limit(limit)
    count_stmt = select(func.count()).select_from(Customer)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
    customers = list(db.scalars(stmt))
    return PaginatedResponse[CustomerResponse](
        total=db.scalar(count_stmt) or 0,
        page=(skip // limit) + 1,
        page_size=limit,
        items=[_customer_response(db, customer) for customer in customers],
    )


@router.post("/masters/customers", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, request: Request, db: Session = Depends(get_db)) -> CustomerResponse:
    if db.scalar(select(Customer.id).where(Customer.customer_number == payload.customer_number)):
        raise AppError("Customer number must be unique.", error_code="duplicate_customer_number", status_code=400)
    customer = Customer(**payload.model_dump(), is_active=True, created_by=request.headers.get("X-User-ID"), updated_by=request.headers.get("X-User-ID"))
    db.add(customer)
    db.flush()
    create_audit_entry(db, table_name="customers", record_id=customer.id, action=AuditAction.CREATE, request=request, after_values=_serialize(customer))
    db.commit()
    db.refresh(customer)
    return _customer_response(db, customer)


@router.get("/masters/cost-centers", response_model=list[CostCenterResponse])
def list_cost_centers(db: Session = Depends(get_db)) -> list[CostCenterResponse]:
    centers = list(db.scalars(select(CostCenter).order_by(CostCenter.code.asc())))
    responses = []
    for center in centers:
        actual_spending = Decimal(
            str(
                db.scalar(
                    select(func.coalesce(func.sum(JournalEntry.debit - JournalEntry.credit), 0)).where(
                        JournalEntry.cost_center_id == center.id,
                        JournalEntry.status != "DRAFT",
                    )
                )
                or 0
            )
        )
        variance = center.budget - actual_spending
        payload = CostCenterResponse.model_validate(center, from_attributes=True).model_dump()
        payload["actual_spending"] = actual_spending
        payload["variance"] = variance
        responses.append(CostCenterResponse.model_validate(payload))
    return responses
