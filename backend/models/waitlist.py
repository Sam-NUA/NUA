from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid


class WaitlistEntryCreate(BaseModel):
    guestName: str
    guestPhone: Optional[str] = None
    partySize: int = 2
    notes: Optional[str] = None
    quotedWait: int = 15  # minutes
    preferences: Optional[str] = None  # indoor, outdoor, bar, etc.


class WaitlistEntryUpdate(BaseModel):
    status: Optional[str] = None
    tableId: Optional[str] = None
    notes: Optional[str] = None
    quotedWait: Optional[int] = None


class WaitlistEntry(BaseModel):
    id: str = ""
    guestName: str
    guestPhone: Optional[str] = None
    partySize: int = 2
    notes: Optional[str] = None
    quotedWait: int = 15
    preferences: Optional[str] = None
    status: str = "waiting"  # waiting, notified, seated, cancelled, left
    position: int = 0
    tableId: Optional[str] = None
    checkInTime: str = ""
    seatedTime: Optional[str] = None
    createdAt: str = ""
    businessId: Optional[str] = None
    # Silver+ tier perk ("Priority waitlist", see routes/loyalty.py's seed
    # tiers) — a recognised member jumps ahead of non-members who joined
    # earlier, but never ahead of an earlier-joined fellow priority guest.
    priority: bool = False

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = f"WL-{str(uuid.uuid4())[:8].upper()}"
        now = datetime.utcnow().isoformat()
        if not self.checkInTime:
            self.checkInTime = now
        if not self.createdAt:
            self.createdAt = now
