"""
Enterprise Accounting — double-entry chart of accounts + journal + derived reports.

Design
──────
• Every value movement in NUA is expressed as a *balanced* journal entry:
     sum(debits) == sum(credits)
• Reports (P&L, Balance Sheet, Cash Flow, Trial Balance, Budget vs Actual)
  are pure aggregations over `journal_lines` — no report ever mutates state.
• Auto-posting hooks convert transactions/refunds/gift-card sales/bills/
  payroll runs into journal entries at the moment they're committed.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
import uuid


AccountType = Literal["asset", "liability", "equity", "revenue", "expense"]


class Account(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    businessId: Optional[str] = None
    code: str                    # e.g. "1000", "4000"
    name: str                    # "Cash at Bank"
    type: AccountType
    subType: Optional[str] = None   # e.g. current_asset, cogs, operating_expense
    parentCode: Optional[str] = None
    currency: str = "AUD"
    isBank: bool = False         # true → included in Bank rec
    isLocked: bool = False       # system accounts cannot be deleted
    description: Optional[str] = None
    active: bool = True
    createdAt: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class JournalLine(BaseModel):
    accountCode: str
    accountName: Optional[str] = None
    debit: float = 0.0
    credit: float = 0.0
    description: Optional[str] = None
    memo: Optional[str] = None
    trackingClass: Optional[str] = None      # e.g. location, department
    contactId: Optional[str] = None          # customer or supplier reference
    currency: str = "AUD"
    fxRate: float = 1.0


class JournalEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    businessId: Optional[str] = None
    journalNumber: Optional[str] = None
    date: str                                # ISO date (YYYY-MM-DD)
    memo: Optional[str] = None
    reference: Optional[str] = None          # e.g. transaction id
    sourceType: str = "manual"               # transaction | refund | gift_card |
                                              # payroll | ap_bill | ap_payment |
                                              # ar_invoice | ar_receipt | deposit |
                                              # deposit_applied | voucher_redeem |
                                              # bank_rec | opening_balance | manual
    sourceRef: Optional[str] = None
    lines: List[JournalLine]
    posted: bool = True
    reversalOf: Optional[str] = None
    createdBy: Optional[str] = None
    createdAt: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ─── Accounts Payable ────────────────────────────────────────────────────
class Bill(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    businessId: Optional[str] = None
    supplierId: str
    supplierName: Optional[str] = None
    billNumber: Optional[str] = None
    issueDate: str
    dueDate: str
    total: float
    gst: float = 0.0
    currency: str = "AUD"
    lines: List[dict] = []           # {accountCode, description, amount, gst}
    status: str = "unpaid"           # unpaid | partial | paid | overdue
    paidAmount: float = 0.0
    journalEntryId: Optional[str] = None
    createdAt: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ─── Accounts Receivable ─────────────────────────────────────────────────
class Invoice(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    businessId: Optional[str] = None
    customerId: str
    customerName: Optional[str] = None
    invoiceNumber: Optional[str] = None
    issueDate: str
    dueDate: str
    total: float
    gst: float = 0.0
    currency: str = "AUD"
    lines: List[dict] = []
    status: str = "unpaid"           # unpaid | partial | paid | overdue
    paidAmount: float = 0.0
    journalEntryId: Optional[str] = None
    createdAt: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ─── Customer deposits (bookings, catering, function deposits) ───────────
class CustomerDeposit(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    businessId: Optional[str] = None
    customerId: str
    customerName: Optional[str] = None
    bookingId: Optional[str] = None
    eventId: Optional[str] = None
    amount: float
    receivedAt: str
    method: str = "card"             # card | bank | cash
    status: str = "held"             # held | applied | refunded
    appliedTransactionId: Optional[str] = None
    createdAt: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ─── Budgets ─────────────────────────────────────────────────────────────
class BudgetLine(BaseModel):
    accountCode: str
    monthlyAmount: float = 0.0


class Budget(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    businessId: Optional[str] = None
    fyStart: str                     # e.g. "2026-07-01"
    fyEnd: str                       # e.g. "2027-06-30"
    name: str = "FY Budget"
    lines: List[BudgetLine] = []
    createdAt: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ─── Bank Reconciliation ─────────────────────────────────────────────────
class BankStatementLine(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    businessId: Optional[str] = None
    accountCode: str                 # bank account code (e.g. 1000)
    statementDate: str
    description: str
    amount: float                    # +ve credit, -ve debit
    balance: Optional[float] = None
    externalId: Optional[str] = None
    matchedJournalLineId: Optional[str] = None
    matchedAt: Optional[str] = None
    ignored: bool = False
