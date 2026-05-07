from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError, ResourceNotFoundError
from app.db.session import get_db
from app.models.enums import AccountType, AuditAction, InventoryAdjustmentReason, PurchaseOrderStatus
from app.models.financial import GLAccount, InventoryItem, InventoryTransaction, PurchaseOrder, PurchaseOrderLineItem, Vendor
from app.schemas.common import PaginatedResponse
from app.schemas.financial import InventoryAdjustRequest, InventoryResponse, PurchaseOrderCreate, PurchaseOrderLineItemResponse, PurchaseOrderReceiveRequest, PurchaseOrderResponse
from app.services.audit import create_audit_entry

router = APIRouter(prefix="/supply-chain", tags=["supply-chain"])


def _serialize(instance) -> dict:
    return {column.name: str(getattr(instance, column.name)) for column in instance.__table__.columns}


def _po_response(po: PurchaseOrder) -> PurchaseOrderResponse:
    total_ordered = sum((line.ordered_quantity for line in po.line_items), Decimal("0.0000"))
    total_received = sum((line.received_quantity for line in po.line_items), Decimal("0.0000"))
    payload = PurchaseOrderResponse.model_validate(po, from_attributes=True).model_dump()
    payload["line_items"] = [PurchaseOrderLineItemResponse.model_validate(line, from_attributes=True).model_dump() for line in po.line_items]
    payload["line_items_count"] = len(po.line_items)
    payload["received_vs_ordered"] = {"received": total_received, "ordered": total_ordered}
    return PurchaseOrderResponse.model_validate(payload)


@router.post("/purchase-orders", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_order(payload: PurchaseOrderCreate, request: Request, db: Session = Depends(get_db)) -> PurchaseOrderResponse:
    vendor = db.scalar(select(Vendor).where(Vendor.id == payload.vendor_id))
    if not vendor:
        raise AppError("Vendor does not exist.", error_code="invalid_vendor", status_code=400)
    po_number = f"PO-{payload.order_date:%Y%m%d}-{uuid4().hex[:6].upper()}"
    total_amount = sum((line.ordered_quantity * line.unit_price for line in payload.line_items), Decimal("0.00"))
    purchase_order = PurchaseOrder(
        po_number=po_number[:30],
        vendor_id=payload.vendor_id,
        order_date=payload.order_date,
        status=PurchaseOrderStatus.OPEN,
        total_amount=total_amount,
        currency=payload.currency,
        created_by=request.headers.get("X-User-ID"),
        updated_by=request.headers.get("X-User-ID"),
    )
    for line in payload.line_items:
        purchase_order.line_items.append(
            PurchaseOrderLineItem(
                item_code=line.item_code,
                description=line.description,
                ordered_quantity=line.ordered_quantity,
                unit_price=line.unit_price,
                line_amount=line.ordered_quantity * line.unit_price,
                created_by=request.headers.get("X-User-ID"),
                updated_by=request.headers.get("X-User-ID"),
            )
        )
    db.add(purchase_order)
    db.flush()
    create_audit_entry(db, table_name="purchase_orders", record_id=purchase_order.id, action=AuditAction.CREATE, request=request, after_values=_serialize(purchase_order))
    db.commit()
    po = db.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.line_items)).where(PurchaseOrder.id == purchase_order.id))
    assert po is not None
    return _po_response(po)


@router.get("/purchase-orders", response_model=PaginatedResponse[PurchaseOrderResponse])
def list_purchase_orders(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    vendor_id: UUID | None = None,
    status_filter: PurchaseOrderStatus | None = Query(default=None, alias="status"),
    from_date: date | None = None,
    to_date: date | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    db: Session = Depends(get_db),
) -> PaginatedResponse[PurchaseOrderResponse]:
    filters = []
    if vendor_id:
        filters.append(PurchaseOrder.vendor_id == vendor_id)
    if status_filter:
        filters.append(PurchaseOrder.status == status_filter)
    if from_date:
        filters.append(PurchaseOrder.order_date >= from_date)
    if to_date:
        filters.append(PurchaseOrder.order_date <= to_date)
    if amount_min is not None:
        filters.append(PurchaseOrder.total_amount >= amount_min)
    if amount_max is not None:
        filters.append(PurchaseOrder.total_amount <= amount_max)
    stmt = select(PurchaseOrder).options(selectinload(PurchaseOrder.line_items)).order_by(PurchaseOrder.order_date.desc()).offset(skip).limit(limit)
    count_stmt = select(func.count()).select_from(PurchaseOrder)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
    pos = list(db.scalars(stmt))
    return PaginatedResponse[PurchaseOrderResponse](total=db.scalar(count_stmt) or 0, page=(skip // limit) + 1, page_size=limit, items=[_po_response(po) for po in pos])


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
def get_purchase_order(po_id: UUID, db: Session = Depends(get_db)) -> PurchaseOrderResponse:
    po = db.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.line_items), selectinload(PurchaseOrder.receipts), selectinload(PurchaseOrder.invoices)).where(PurchaseOrder.id == po_id))
    if not po:
        raise ResourceNotFoundError("Purchase order not found.")
    return _po_response(po)


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderResponse)
def receive_purchase_order(po_id: UUID, payload: PurchaseOrderReceiveRequest, request: Request, db: Session = Depends(get_db)) -> PurchaseOrderResponse:
    po = db.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.line_items)).where(PurchaseOrder.id == po_id))
    if not po:
        raise ResourceNotFoundError("Purchase order not found.")
    user_id = request.headers.get("X-User-ID")
    inventory_account = db.scalar(select(GLAccount).where(GLAccount.account_type == AccountType.ASSET).order_by(GLAccount.account_number.asc()))
    for receipt in payload.receipts:
        item_code = receipt["item_code"]
        qty = Decimal(str(receipt["quantity"]))
        line = next((line for line in po.line_items if line.item_code == item_code), None)
        if not line:
            raise AppError("PO line item not found for receipt.", error_code="invalid_receipt", status_code=400)
        line.received_quantity += qty
        inventory = db.scalar(select(InventoryItem).where(InventoryItem.item_code == item_code, InventoryItem.warehouse == "MAIN"))
        if not inventory:
            inventory = InventoryItem(item_code=item_code, item_name=line.description, warehouse="MAIN", quantity_on_hand=Decimal("0.0000"), reorder_point=Decimal("0.0000"), reorder_quantity=Decimal("0.0000"), created_by=user_id, updated_by=user_id)
            db.add(inventory)
            db.flush()
        inventory.quantity_on_hand += qty
        inventory.last_receipt_date = date.today()
        inventory.updated_by = user_id
        db.add(InventoryTransaction(inventory_item_id=inventory.id, purchase_order_id=po.id, quantity=qty, reason=InventoryAdjustmentReason.RECEIPT, transaction_date=date.today(), notes=payload.notes, created_by=user_id, updated_by=user_id))
        if inventory_account:
            inventory_account.balance += qty * line.unit_price
            inventory_account.updated_by = user_id
    po.status = PurchaseOrderStatus.RECEIVED if all(line.received_quantity >= line.ordered_quantity for line in po.line_items) else PurchaseOrderStatus.PARTIALLY_RECEIVED
    create_audit_entry(db, table_name="purchase_orders", record_id=po.id, action=AuditAction.UPDATE, request=request, after_values={"event": "receive", "notes": payload.notes, "status": po.status.value})
    db.commit()
    po = db.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.line_items)).where(PurchaseOrder.id == po.id))
    assert po is not None
    return _po_response(po)


@router.get("/inventory", response_model=PaginatedResponse[InventoryResponse])
def list_inventory(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    warehouse: str | None = None,
    item_id: UUID | None = None,
    search: str | None = None,
    low_stock: bool = False,
    db: Session = Depends(get_db),
) -> PaginatedResponse[InventoryResponse]:
    filters = []
    if warehouse:
        filters.append(InventoryItem.warehouse == warehouse)
    if item_id:
        filters.append(InventoryItem.id == item_id)
    if search:
        value = f"%{search}%"
        filters.append(or_(InventoryItem.item_code.ilike(value), InventoryItem.item_name.ilike(value)))
    if low_stock:
        filters.append(InventoryItem.quantity_on_hand <= InventoryItem.reorder_point)
    stmt = select(InventoryItem).order_by(InventoryItem.item_code.asc()).offset(skip).limit(limit)
    count_stmt = select(func.count()).select_from(InventoryItem)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
    items = list(db.scalars(stmt))
    responses = []
    for item in items:
        stock_status = "OUT_OF_STOCK" if item.quantity_on_hand <= 0 else "LOW_STOCK" if item.quantity_on_hand <= item.reorder_point else "IN_STOCK"
        payload = InventoryResponse.model_validate(item, from_attributes=True).model_dump()
        payload["status"] = stock_status
        responses.append(InventoryResponse.model_validate(payload))
    return PaginatedResponse[InventoryResponse](total=db.scalar(count_stmt) or 0, page=(skip // limit) + 1, page_size=limit, items=responses)


@router.post("/inventory/adjust", response_model=InventoryResponse)
def adjust_inventory(payload: InventoryAdjustRequest, request: Request, db: Session = Depends(get_db)) -> InventoryResponse:
    inventory = db.scalar(select(InventoryItem).where(InventoryItem.item_code == payload.item_code, InventoryItem.warehouse == payload.warehouse))
    user_id = request.headers.get("X-User-ID")
    if not inventory:
        inventory = InventoryItem(item_code=payload.item_code, item_name=payload.item_name or payload.item_code, warehouse=payload.warehouse, quantity_on_hand=Decimal("0.0000"), reorder_point=Decimal("0.0000"), reorder_quantity=Decimal("0.0000"), created_by=user_id, updated_by=user_id)
        db.add(inventory)
        db.flush()
    inventory.quantity_on_hand += payload.quantity
    if payload.reason == InventoryAdjustmentReason.RECEIPT:
        inventory.last_receipt_date = date.today()
    if payload.reason in {InventoryAdjustmentReason.ISSUE, InventoryAdjustmentReason.SHRINKAGE, InventoryAdjustmentReason.DAMAGE}:
        inventory.last_issue_date = date.today()
    inventory.updated_by = user_id
    db.add(InventoryTransaction(inventory_item_id=inventory.id, quantity=payload.quantity, reason=payload.reason, transaction_date=date.today(), notes=payload.notes, created_by=user_id, updated_by=user_id))
    create_audit_entry(db, table_name="inventory_items", record_id=inventory.id, action=AuditAction.UPDATE, request=request, after_values={"event": "adjust", "quantity": str(payload.quantity), "reason": payload.reason.value})
    db.commit()
    stock_status = "OUT_OF_STOCK" if inventory.quantity_on_hand <= 0 else "LOW_STOCK" if inventory.quantity_on_hand <= inventory.reorder_point else "IN_STOCK"
    payload_dict = InventoryResponse.model_validate(inventory, from_attributes=True).model_dump()
    payload_dict["status"] = stock_status
    return InventoryResponse.model_validate(payload_dict)
