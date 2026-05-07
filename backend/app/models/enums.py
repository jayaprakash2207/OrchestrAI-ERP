from enum import Enum


class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class APInvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    PAID = "PAID"
    VOID = "VOID"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class JournalEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PurchaseOrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class InventoryAdjustmentReason(str, Enum):
    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    ADJUSTMENT = "ADJUSTMENT"
    SHRINKAGE = "SHRINKAGE"
    DAMAGE = "DAMAGE"


class AuditAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
