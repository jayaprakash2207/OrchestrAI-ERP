import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base, TimestampAuditMixin
from app.models.enums import (
    APInvoiceStatus,
    AccountType,
    ApprovalStatus,
    AuditAction,
    InventoryAdjustmentReason,
    JournalEntryStatus,
    PurchaseOrderStatus,
)


class CostCenter(TimestampAuditMixin, Base):
    __tablename__ = "cost_centers"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    gl_accounts: Mapped[list["GLAccount"]] = relationship(back_populates="cost_center")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="cost_center")

    __table_args__ = (CheckConstraint("budget >= 0", name="ck_cost_centers_budget_non_negative"),)


class GLAccount(TimestampAuditMixin, Base):
    __tablename__ = "gl_accounts"

    account_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType, name="account_type"), nullable=False)
    parent_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("gl_accounts.id", ondelete="SET NULL"), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    ytd_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    ytd_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_centers.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    parent_account: Mapped["GLAccount | None"] = relationship("GLAccount", remote_side="GLAccount.id", back_populates="child_accounts")
    child_accounts: Mapped[list["GLAccount"]] = relationship("GLAccount", back_populates="parent_account")
    cost_center: Mapped[CostCenter | None] = relationship(back_populates="gl_accounts")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="account")

    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_gl_accounts_balance_non_negative"),
        CheckConstraint("ytd_debit >= 0", name="ck_gl_accounts_ytd_debit_non_negative"),
        CheckConstraint("ytd_credit >= 0", name="ck_gl_accounts_ytd_credit_non_negative"),
        Index("ix_gl_accounts_account_number", "account_number"),
        Index("ix_gl_accounts_account_type", "account_type"),
        Index("ix_gl_accounts_parent_account_id", "parent_account_id"),
    )

    @validates("account_number")
    def validate_account_number(self, _key: str, value: str) -> str:
        if not value or not value.isalnum():
            raise ValueError("Account number must be alphanumeric.")
        return value.upper()


class Vendor(TimestampAuditMixin, Base):
    __tablename__ = "vendors"

    vendor_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    invoices: Mapped[list["APInvoice"]] = relationship(back_populates="vendor")

    __table_args__ = (
        CheckConstraint("payment_terms_days >= 0", name="ck_vendors_payment_terms_non_negative"),
        CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 5)", name="ck_vendors_rating_range"),
    )

    @hybrid_property
    def total_spending(self) -> Decimal:
        return sum((invoice.amount for invoice in self.invoices if invoice.status in {APInvoiceStatus.POSTED, APInvoiceStatus.PAID}), Decimal("0.00"))


class Customer(TimestampAuditMixin, Base):
    __tablename__ = "customers"

    customer_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        CheckConstraint("credit_limit >= 0", name="ck_customers_credit_limit_non_negative"),
        CheckConstraint("payment_terms_days >= 0", name="ck_customers_payment_terms_non_negative"),
    )

    ar_invoices: Mapped[list["ARInvoice"]] = relationship(back_populates="customer")


class APInvoice(TimestampAuditMixin, Base):
    __tablename__ = "ap_invoices"

    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[APInvoiceStatus] = mapped_column(Enum(APInvoiceStatus, name="ap_invoice_status"), nullable=False, default=APInvoiceStatus.DRAFT, server_default=APInvoiceStatus.DRAFT.value)
    approval_status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus, name="approval_status"), nullable=False, default=ApprovalStatus.PENDING, server_default=ApprovalStatus.PENDING.value)
    approval_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    vendor: Mapped[Vendor] = relationship(back_populates="invoices")
    line_items: Mapped[list["APInvoiceLineItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    approvals: Mapped[list["APInvoiceApproval"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True)
    purchase_order: Mapped["PurchaseOrder | None"] = relationship(back_populates="invoices")

    __table_args__ = (
        UniqueConstraint("vendor_id", "invoice_number", name="uq_ap_invoices_vendor_invoice_number"),
        CheckConstraint("amount > 0", name="ck_ap_invoices_amount_positive"),
        CheckConstraint("approval_level >= 1", name="ck_ap_invoices_approval_level_positive"),
        CheckConstraint("due_date >= invoice_date", name="ck_ap_invoices_due_date_after_invoice_date"),
        Index("ix_ap_invoices_vendor_id", "vendor_id"),
        Index("ix_ap_invoices_invoice_number", "invoice_number"),
        Index("ix_ap_invoices_status", "status"),
        Index("ix_ap_invoices_due_date", "due_date"),
    )

    @property
    def days_overdue(self) -> int:
        if self.status == APInvoiceStatus.PAID:
            return 0
        return max((date.today() - self.due_date).days, 0)


class APInvoiceLineItem(TimestampAuditMixin, Base):
    __tablename__ = "ap_invoice_line_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ap_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1.0000"), server_default="1")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gl_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("gl_accounts.id", ondelete="SET NULL"), nullable=True)

    invoice: Mapped[APInvoice] = relationship(back_populates="line_items")
    gl_account: Mapped[GLAccount | None] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_ap_invoice_line_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_ap_invoice_line_items_unit_price_non_negative"),
        CheckConstraint("amount >= 0", name="ck_ap_invoice_line_items_amount_non_negative"),
    )


class JournalEntry(TimestampAuditMixin, Base):
    __tablename__ = "journal_entries"

    journal_batch_id: Mapped[str] = mapped_column(String(50), nullable=False)
    journal_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gl_accounts.id", ondelete="RESTRICT"), nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cost_centers.id", ondelete="SET NULL"), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    status: Mapped[JournalEntryStatus] = mapped_column(Enum(JournalEntryStatus, name="journal_entry_status"), nullable=False, default=JournalEntryStatus.DRAFT, server_default=JournalEntryStatus.DRAFT.value)

    account: Mapped[GLAccount] = relationship(back_populates="journal_entries")
    cost_center: Mapped[CostCenter | None] = relationship(back_populates="journal_entries")

    __table_args__ = (
        CheckConstraint("debit >= 0", name="ck_journal_entries_debit_non_negative"),
        CheckConstraint("credit >= 0", name="ck_journal_entries_credit_non_negative"),
        CheckConstraint("NOT (debit = 0 AND credit = 0)", name="ck_journal_entries_non_zero"),
        CheckConstraint("NOT (debit > 0 AND credit > 0)", name="ck_journal_entries_one_sided"),
        Index("ix_journal_entries_batch_id", "journal_batch_id"),
        Index("ix_journal_entries_account_id", "account_id"),
        Index("ix_journal_entries_journal_date", "journal_date"),
    )

    @validates("currency")
    def validate_currency(self, _key: str, value: str) -> str:
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code.")
        return value.upper()


class APInvoiceApproval(TimestampAuditMixin, Base):
    __tablename__ = "ap_invoice_approvals"

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ap_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    approval_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    approved_by: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    invoice: Mapped[APInvoice] = relationship(back_populates="approvals")

    __table_args__ = (
        CheckConstraint("approval_level >= 1", name="ck_ap_invoice_approvals_level_positive"),
    )


class ARInvoice(TimestampAuditMixin, Base):
    __tablename__ = "ar_invoices"

    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[APInvoiceStatus] = mapped_column(Enum(APInvoiceStatus, name="ar_invoice_status"), nullable=False, default=APInvoiceStatus.POSTED, server_default=APInvoiceStatus.POSTED.value)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="ar_invoices")

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_ar_invoices_amount_positive"),
        CheckConstraint("due_date >= invoice_date", name="ck_ar_invoices_due_date_after_invoice_date"),
    )


class PurchaseOrder(TimestampAuditMixin, Base):
    __tablename__ = "purchase_orders"

    po_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    status: Mapped[PurchaseOrderStatus] = mapped_column(Enum(PurchaseOrderStatus, name="purchase_order_status"), nullable=False, default=PurchaseOrderStatus.OPEN, server_default=PurchaseOrderStatus.OPEN.value)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")

    vendor: Mapped[Vendor] = relationship()
    line_items: Mapped[list["PurchaseOrderLineItem"]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")
    receipts: Mapped[list["InventoryTransaction"]] = relationship(back_populates="purchase_order")
    invoices: Mapped[list[APInvoice]] = relationship(back_populates="purchase_order")

    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_purchase_orders_total_amount_non_negative"),
    )


class PurchaseOrderLineItem(TimestampAuditMixin, Base):
    __tablename__ = "purchase_order_line_items"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    item_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"), server_default="0")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="line_items")

    __table_args__ = (
        CheckConstraint("ordered_quantity > 0", name="ck_purchase_order_line_items_ordered_qty_positive"),
        CheckConstraint("received_quantity >= 0", name="ck_purchase_order_line_items_received_qty_non_negative"),
        CheckConstraint("unit_price >= 0", name="ck_purchase_order_line_items_unit_price_non_negative"),
        CheckConstraint("line_amount >= 0", name="ck_purchase_order_line_items_amount_non_negative"),
    )


class InventoryItem(TimestampAuditMixin, Base):
    __tablename__ = "inventory_items"

    item_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    warehouse: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"), server_default="0")
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"), server_default="0")
    reorder_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"), server_default="0")
    last_receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    transactions: Mapped[list["InventoryTransaction"]] = relationship(back_populates="inventory_item")


class InventoryTransaction(TimestampAuditMixin, Base):
    __tablename__ = "inventory_transactions"

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    reason: Mapped[InventoryAdjustmentReason] = mapped_column(Enum(InventoryAdjustmentReason, name="inventory_adjustment_reason"), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    inventory_item: Mapped[InventoryItem] = relationship(back_populates="transactions")
    purchase_order: Mapped[PurchaseOrder | None] = relationship(back_populates="receipts")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction, name="audit_action"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    before_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_audit_logs_table_record", "table_name", "record_id"),)
