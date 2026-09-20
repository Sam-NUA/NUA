from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import uuid


class KitchenOrderItem(BaseModel):
    productId: str = ""
    productName: str = ""
    quantity: int = 1
    modifiers: List[dict] = []
    notes: Optional[str] = None
    course: int = 1  # 1=starter, 2=main, 3=dessert
    seat: Optional[int] = None   # which guest ordered it, so runners don't ask
    round: int = 1               # which trip to the table this was rung on
    status: str = "pending"  # pending, preparing, ready


class SeatNote(BaseModel):
    seat: int
    note: str
    tag: str = "note"  # allergen | dietary | note — drives the KDS warning styling


class KitchenOrderCreate(BaseModel):
    businessId: Optional[str] = None
    transactionId: Optional[str] = None
    reservationId: Optional[str] = None
    tableNumber: Optional[str] = None
    orderType: str = "dine_in"  # dine_in, takeaway, delivery
    items: List[dict] = []
    notes: Optional[str] = None
    seatNotes: List[SeatNote] = []  # per-seat allergen/dietary/custom notes
    priority: str = "normal"  # normal, rush, vip
    serverId: Optional[str] = None
    covers: Optional[int] = None
    deviceLabel: Optional[str] = None  # e.g. "Front POS", "Tablet 3", "Online"
    deviceId: Optional[str] = None
    createdByName: Optional[str] = None
    createdByEmail: Optional[str] = None


class KitchenOrder(BaseModel):
    id: str = ""
    businessId: Optional[str] = None
    transactionId: Optional[str] = None
    reservationId: Optional[str] = None
    tableNumber: Optional[str] = None
    orderType: str = "dine_in"
    items: List[dict] = []
    notes: Optional[str] = None
    seatNotes: List[SeatNote] = []
    priority: str = "normal"
    status: str = "new"  # new, preparing, ready, served, cancelled
    serverId: Optional[str] = None
    currentCourse: int = 1

    # ── Enriched docket fields (v33) ──
    covers: Optional[int] = None
    deviceLabel: Optional[str] = None
    deviceId: Optional[str] = None
    createdByName: Optional[str] = None
    createdByEmail: Optional[str] = None
    guestName: Optional[str] = None            # from reservation

    # ── Per-course lifecycle (v33) ──
    # Keys are course numbers as strings ("1","2","3"). Each course has:
    #   { status: "held"|"queued"|"fired"|"ready"|"served",
    #     heldAt, firedAt, firedBy, readyAt, servedAt }
    courses: Dict[str, Any] = {}

    # How many times the table has ordered onto this ticket. A long dinner
    # adds dessert an hour after the mains; that's a second round on the same
    # ticket, not a second ticket.
    rounds: int = 1

    # Append-only trail of every course state change:
    #   { course, from, to, at, by }
    # The `courses` map only keeps the latest timestamp per state, so a course
    # held twice, or re-fired after a hold, loses its earlier history — and
    # "how long did mains sit at the pass?" becomes unanswerable.
    courseHistory: List[dict] = []

    createdAt: str = ""
    startedAt: Optional[str] = None
    readyAt: Optional[str] = None
    servedAt: Optional[str] = None
    estimatedMinutes: int = 15

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = f"KO-{str(uuid.uuid4())[:8].upper()}"
        if not self.createdAt:
            self.createdAt = datetime.now(timezone.utc).isoformat()
        # Auto-seed the courses map from items so each distinct course starts
        # in a known state ("queued" — will fire in the natural order, unless
        # explicitly held).
        if not self.courses:
            seen = set()
            for it in self.items or []:
                c = str(it.get("course") or 1)
                if c not in seen:
                    seen.add(c)
                    self.courses[c] = {"status": "queued",
                                        "heldAt": None, "firedAt": None,
                                        "firedBy": None, "servedAt": None}
