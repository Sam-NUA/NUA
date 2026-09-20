from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import uuid

class BASReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    businessId: str
    quarter: str
    period: str
    totalSales: float
    gstCollected: float
    gstPaid: float
    netGst: float
    status: str = "draft"  # draft or submitted
    submittedDate: Optional[datetime] = None
    dueDate: datetime
    transactionIds: List[str] = []
    createdAt: datetime = Field(default_factory=datetime.utcnow)

class BASReportCreate(BaseModel):
    quarter: str
    period: str
    dueDate: datetime
