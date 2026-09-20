from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid

class Supplier(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    contactPerson: str
    email: str
    phone: str
    address: str
    paymentTerms: str  # "Net 30", "COD", etc
    status: str = "active"
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    businessId: Optional[str] = None

class SupplierCreate(BaseModel):
    name: str
    contactPerson: str
    email: str
    phone: str
    address: str
    paymentTerms: str

class PurchaseOrder(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    supplierId: str
    supplierName: str
    orderDate: datetime = Field(default_factory=datetime.utcnow)
    expectedDelivery: Optional[datetime] = None
    items: list
    subtotal: float
    gst: float
    total: float
    status: str = "pending"  # pending, received, cancelled
    notes: Optional[str] = None
    businessId: Optional[str] = None

class PurchaseOrderCreate(BaseModel):
    supplierId: str
    expectedDelivery: Optional[datetime] = None
    items: list
    notes: Optional[str] = None
