from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationInfo, model_validator

from app.models.enums import APInvoiceStatus, AccountType, ApprovalStatus, InventoryAdjustmentReason, JournalEntryStatus, PurchaseOrderStatus
from app.schemas.common import BaseSchema


class CostCenterSummary(BaseSchema):
    code: str
    name: str
    manager_id: str | None = None
    budget: Decimal
    is_active: bool


class GLAccountCreate(BaseModel):
    account_number: str = Field(..., min_length=1, max_length=20, pattern=r"^[A-Za-z0-9]+$", examples=["1000"])
    account_name: str = Field(..., min_length=1, max_length=255, examples=["Cash and Cash Equivalents"])
    account_type: AccountType = Field(..., examples=["ASSET"])
    parent_account_id: UUID | None = Field(default=None)
    cost_center_id: UUID | None = Field(default=None)
    is_active: bool = Field(default=True)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "account_number": "1000",
                "account_name": "Cash and Cash Equivalents",
                "account_type": "ASSET",
                "parent_account_id": None,
                "cost_center_id": None,
                "is_active": True,
            }
        }
    )


class GLAccountSummary(BaseSchema):
    account_number: str
    account_name: str
    account_type: AccountType
    parent_account_id: UUID | None = None
    cost_center_id: UUID | None = None
    is_active: bool
    balance: Decimal
    ytd_debit: Decimal
    ytd_credit: Decimal


class GLAccountResponse(BaseSchema):
    account_number: str
    account_name: str
    account_type: AccountType
    parent_account_id: UUID | None = None
    cost_center_id: UUID | None = None
    is_active: bool
    balance: Decimal
    ytd_debit: Decimal
    ytd_credit: Decimal
    parent_account: GLAccountSummary | None = None
    child_accounts: list[GLAccountSummary] = Field(default_factory=list)
    cost_center: CostCenterSummary | None = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "80d11926-ec3a-4674-90f1-337b15aeb53b",
                "created_at": "2026-04-06T12:00:00Z",
                "updated_at": "2026-04-06T12:00:00Z",
                "created_by": "finance.admin",
                "updated_by": "finance.admin",
                "account_number": "1000",
                "account_name": "Cash and Cash Equivalents",
                "account_type": "ASSET",
                "parent_account_id": None,
                "cost_center_id": None,
                "is_active": True,
                "balance": "10000.00",
                "ytd_debit": "5000.00",
                "ytd_credit": "1000.00",
                "parent_account": None,
                "child_accounts": [],
                "cost_center": None,
            }
        },
    )


class APInvoiceLineItemCreate(BaseModel):
    description: str = Field(..., min_length=1, max_length=255, examples=["Office supplies"])
    quantity: Decimal = Field(..., gt=0, examples=["2.0000"])
    unit_price: Decimal = Field(..., ge=0, examples=["50.00"])
    amount: Decimal = Field(..., ge=0, examples=["100.00"])
    gl_account_id: UUID | None = Field(default=None)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "description": "Office supplies",
                "quantity": "2.0000",
                "unit_price": "50.00",
                "amount": "100.00",
                "gl_account_id": None,
            }
        }
    )


class APInvoiceLineItemResponse(BaseSchema):
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    gl_account_id: UUID | None = None
    gl_account: GLAccountSummary | None = None


class APInvoiceCreate(BaseModel):
    invoice_number: str = Field(..., min_length=1, max_length=50, examples=["INV-2026-0001"])
    vendor_id: UUID
    amount: Decimal = Field(..., gt=0, examples=["1000.00"])
    currency: str = Field(..., pattern=r"^[A-Z]{3}$", examples=["USD"])
    invoice_date: date
    due_date: date
    line_items: list[APInvoiceLineItemCreate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_invoice_totals(self) -> "APInvoiceCreate":
        if self.due_date < self.invoice_date:
            raise ValueError("Due date must be on or after invoice date.")
        line_total = sum((item.amount for item in self.line_items), Decimal("0.00"))
        if line_total != self.amount:
            raise ValueError(f"Line items total {line_total} must equal invoice amount {self.amount}.")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "invoice_number": "INV-2026-0001",
                "vendor_id": "0efaadcb-6f52-4038-8d39-2b1e11661111",
                "amount": "1000.00",
                "currency": "USD",
                "invoice_date": "2026-04-01",
                "due_date": "2026-04-30",
                "line_items": [
                    {
                        "description": "Implementation services",
                        "quantity": "1.0000",
                        "unit_price": "1000.00",
                        "amount": "1000.00",
                        "gl_account_id": None,
                    }
                ],
            }
        }
    )


class APInvoiceResponse(BaseSchema):
    invoice_number: str
    vendor_id: UUID
    amount: Decimal
    currency: str
    invoice_date: date
    due_date: date
    line_items: list[APInvoiceLineItemResponse] = Field(default_factory=list)
    status: APInvoiceStatus
    approval_status: ApprovalStatus
    approval_level: int
    payment_date: date | None = None
    payment_method: str | None = None
    days_overdue: int = Field(..., ge=0)

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "7c5d4fc8-8b88-4f7c-918f-d01a52c01c9f",
                "created_at": "2026-04-06T12:00:00Z",
                "updated_at": "2026-04-06T12:00:00Z",
                "created_by": "ap.clerk",
                "updated_by": "ap.manager",
                "invoice_number": "INV-2026-0001",
                "vendor_id": "0efaadcb-6f52-4038-8d39-2b1e11661111",
                "amount": "1000.00",
                "currency": "USD",
                "invoice_date": "2026-04-01",
                "due_date": "2026-04-30",
                "line_items": [],
                "status": "POSTED",
                "approval_status": "APPROVED",
                "approval_level": 2,
                "payment_date": None,
                "payment_method": None,
                "days_overdue": 0,
            }
        },
    )


class JournalEntrySummary(BaseSchema):
    journal_batch_id: str
    journal_date: date
    account_id: UUID
    debit: Decimal
    credit: Decimal
    description: str | None = None
    cost_center_id: UUID | None = None
    currency: str
    status: JournalEntryStatus
    account_name: str | None = None
    account_type: AccountType | None = None
    running_balance: Decimal | None = None


class GLAccountDetailResponse(GLAccountResponse):
    transactions: list[JournalEntrySummary] = Field(default_factory=list)


class JournalEntryCreate(BaseModel):
    journal_batch_id: str = Field(..., min_length=1, max_length=50, examples=["JB-2026-0001"])
    journal_date: date
    account_id: UUID
    debit: Decimal = Field(default=Decimal("0.00"), ge=0, examples=["100.00"])
    credit: Decimal = Field(default=Decimal("0.00"), ge=0, examples=["0.00"])
    description: str | None = Field(default=None, max_length=1000)
    cost_center_id: UUID | None = Field(default=None)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$", examples=["USD"])

    @model_validator(mode="after")
    def validate_amounts(self) -> "JournalEntryCreate":
        if self.debit + self.credit <= 0:
            raise ValueError("Debit and credit cannot both be zero.")
        if self.debit > 0 and self.credit > 0:
            raise ValueError("Only one of debit or credit may be greater than zero.")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "journal_batch_id": "JB-2026-0001",
                "journal_date": "2026-04-06",
                "account_id": "80d11926-ec3a-4674-90f1-337b15aeb53b",
                "debit": "100.00",
                "credit": "0.00",
                "description": "Office supplies accrual",
                "cost_center_id": None,
                "currency": "USD",
            }
        }
    )


class JournalBatchPost(BaseModel):
    batch_id: str = Field(..., min_length=1, max_length=50, examples=["JB-2026-0001"])

    @model_validator(mode="after")
    def validate_balanced_batch(self, info: ValidationInfo) -> "JournalBatchPost":
        context = info.context or {}
        batch_totals = context.get("batch_totals")
        if batch_totals is None:
            return self

        total_debit = Decimal(str(batch_totals.get("total_debit", "0")))
        total_credit = Decimal(str(batch_totals.get("total_credit", "0")))
        entry_count = int(batch_totals.get("entry_count", 0))

        if entry_count == 0:
            raise ValueError(f"Journal batch {self.batch_id} has no entries to post.")
        if total_debit != total_credit:
            raise ValueError(
                f"Journal batch {self.batch_id} is unbalanced. total_debit={total_debit}, total_credit={total_credit}"
            )
        return self

    model_config = ConfigDict(json_schema_extra={"example": {"batch_id": "JB-2026-0001"}})


class JournalEntryCreateRequest(BaseModel):
    journal_batch_id: str | None = Field(default=None, max_length=50, examples=["JB-2026-0001"])
    journal_date: date
    account_id: UUID
    debit: Decimal = Field(default=Decimal("0.00"), ge=0)
    credit: Decimal = Field(default=Decimal("0.00"), ge=0)
    description: str | None = Field(default=None, max_length=1000)
    cost_center_id: UUID | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def validate_entry_amounts(self) -> "JournalEntryCreateRequest":
        if self.debit + self.credit <= 0:
            raise ValueError("Either debit or credit must be greater than zero.")
        if self.debit > 0 and self.credit > 0:
            raise ValueError("Only one of debit or credit may be provided.")
        return self


class JournalBatchValidationResponse(BaseModel):
    batch_id: str
    total_debit: Decimal
    total_credit: Decimal
    difference: Decimal
    is_balanced: bool
    message: str


class JournalBatchDetailResponse(BaseModel):
    batch_id: str
    status: str
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool
    posting_information: dict | None = None
    entries: list[JournalEntrySummary]


class TrialBalanceAccountLine(BaseModel):
    account_id: UUID
    account_number: str
    account_name: str
    account_type: AccountType
    debit_balance: Decimal
    credit_balance: Decimal


class TrialBalanceResponse(BaseModel):
    as_of_date: date
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool
    accounts: list[TrialBalanceAccountLine]


class FinancialStatementAccountLine(BaseModel):
    account_id: UUID
    account_number: str
    account_name: str
    amount: Decimal
    cost_center_code: str | None = None


class FinancialStatementSection(BaseModel):
    total: Decimal
    current: Decimal | None = None
    accounts: list[FinancialStatementAccountLine] = Field(default_factory=list)
    cost_centers: list[dict] | None = None


class BalanceSheetResponse(BaseModel):
    as_of_date: date
    assets: FinancialStatementSection
    liabilities: FinancialStatementSection
    equity: FinancialStatementSection
    total_liabilities_and_equity: Decimal


class IncomeStatementResponse(BaseModel):
    period: dict
    revenue: FinancialStatementSection
    expenses: FinancialStatementSection
    operating_income: Decimal
    other_income: Decimal
    other_expense: Decimal
    net_income: Decimal


class AgingBucket(BaseModel):
    days_overdue: str
    count: int
    amount: Decimal
    percent: Decimal


class APAgingDetail(BaseModel):
    invoice_number: str
    vendor: str
    amount: Decimal
    due_date: date
    days_overdue: int
    currency: str


class APAgingResponse(BaseModel):
    as_of_date: date
    total_ap: Decimal
    aging_buckets: list[AgingBucket]
    details: list[APAgingDetail]


class ARAgingDetail(BaseModel):
    invoice_number: str
    customer: str
    amount: Decimal
    due_date: date
    days_overdue: int
    currency: str


class ARAgingResponse(BaseModel):
    as_of_date: date
    total_ar: Decimal
    aging_buckets: list[AgingBucket]
    details: list[ARAgingDetail]


class GLDetailResponse(BaseModel):
    account: GLAccountSummary
    from_date: date
    to_date: date
    transactions: list[JournalEntrySummary]


class ApprovalHistoryResponse(BaseSchema):
    invoice_id: UUID
    approval_level: int
    approved_by: str
    notes: str | None = None
    approved_at: datetime | None = None


class VendorSummary(BaseSchema):
    vendor_number: str
    vendor_name: str
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    tax_id: str | None = None
    payment_terms_days: int
    is_active: bool
    rating: int | None = Field(default=None, ge=0, le=5)
    total_spending: Decimal = Decimal("0.00")


class VendorResponse(BaseSchema):
    vendor_number: str
    vendor_name: str
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    tax_id: str | None = None
    payment_terms_days: int
    is_active: bool
    rating: int | None = Field(default=None, ge=0, le=5)
    total_spending: Decimal = Decimal("0.00")


class CustomerResponse(BaseSchema):
    customer_number: str
    customer_name: str
    email: EmailStr | None = None
    phone: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    credit_limit: Decimal
    payment_terms_days: int
    is_active: bool


class VendorCreate(BaseModel):
    vendor_number: str = Field(..., min_length=1, max_length=20)
    vendor_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    tax_id: str | None = None
    payment_terms_days: int = Field(default=30, ge=0)
    rating: int | None = Field(default=None, ge=0, le=5)


class CustomerCreate(BaseModel):
    customer_number: str = Field(..., min_length=1, max_length=20)
    customer_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    credit_limit: Decimal = Field(default=Decimal("0.00"), ge=0)
    payment_terms_days: int = Field(default=30, ge=0)


class CostCenterResponse(BaseSchema):
    code: str
    name: str
    manager_id: str | None = None
    budget: Decimal
    is_active: bool
    actual_spending: Decimal = Decimal("0.00")
    variance: Decimal = Decimal("0.00")


class PurchaseOrderLineItemCreate(BaseModel):
    item_code: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=1, max_length=255)
    ordered_quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class PurchaseOrderCreate(BaseModel):
    vendor_id: UUID
    order_date: date = Field(default_factory=date.today)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    line_items: list[PurchaseOrderLineItemCreate] = Field(..., min_length=1)


class PurchaseOrderLineItemResponse(BaseSchema):
    item_code: str
    description: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    unit_price: Decimal
    line_amount: Decimal


class PurchaseOrderResponse(BaseSchema):
    po_number: str
    vendor_id: UUID
    order_date: date
    status: PurchaseOrderStatus
    total_amount: Decimal
    currency: str
    line_items: list[PurchaseOrderLineItemResponse] = Field(default_factory=list)
    line_items_count: int = 0
    received_vs_ordered: dict[str, Decimal] | None = None


class PurchaseOrderReceiveRequest(BaseModel):
    receipts: list[dict] = Field(..., min_length=1, examples=[[{"item_code": "ITEM-001", "quantity": "5.0000"}]])
    notes: str | None = None


class InventoryResponse(BaseSchema):
    item_code: str
    item_name: str
    warehouse: str
    quantity_on_hand: Decimal
    reorder_point: Decimal
    reorder_quantity: Decimal
    last_receipt_date: date | None = None
    last_issue_date: date | None = None
    status: str


class InventoryAdjustRequest(BaseModel):
    item_code: str = Field(..., min_length=1, max_length=50)
    item_name: str | None = None
    warehouse: str = Field(..., min_length=1, max_length=100)
    quantity: Decimal
    reason: InventoryAdjustmentReason
    notes: str | None = None


class APInvoiceDetailResponse(APInvoiceResponse):
    vendor: VendorSummary
    approval_history: list[ApprovalHistoryResponse] = Field(default_factory=list)


class GLAccountUpdate(BaseModel):
    account_name: str | None = Field(default=None, min_length=1, max_length=255)
    cost_center_id: UUID | None = None
    is_active: bool | None = None
    parent_account_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")


class APInvoiceApproveRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)


class APInvoicePaymentRequest(BaseModel):
    payment_method: str = Field(..., min_length=1, max_length=50, examples=["WIRE"])
    payment_date: date = Field(default_factory=date.today)


class APInvoiceVoidRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000, examples=["Duplicate invoice"])
