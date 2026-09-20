from pydantic import BaseModel, model_validator
from typing import Optional, List
from datetime import datetime
import uuid


class ReservationCreate(BaseModel):
    guestName: str
    guestPhone: Optional[str] = None
    guestEmail: Optional[str] = None
    customerId: Optional[str] = None
    partySize: int = 2
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    duration: int = 90  # minutes
    tableId: Optional[str] = None
    tableNumber: Optional[str] = None
    floorPlanId: Optional[str] = None
    section: Optional[str] = None
    specialRequests: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = []
    depositRequired: float = 0
    depositPaid: bool = False
    serverId: Optional[str] = None
    source: str = "walk_in"  # walk_in, phone, online, app
    # Large-booking / booking-size-rules inputs — validated server-side by
    # services.booking_rules_engine, never trusted as-is (a caller can send
    # experienceId, but whether it's ACTUALLY required/allowed for this
    # party size is decided by the engine, not by what's in this payload).
    experienceId: Optional[str] = None
    preOrderNotes: Optional[str] = None
    # A deliberate staff override of a booking-rule violation (large-booking
    # tier, capacity, or booking window). Requires owner/manager and is
    # audit-logged — distinct from "no rule was checked", which is what
    # would let a rule be bypassed *accidentally*.
    overrideReason: Optional[str] = None


class ReservationUpdate(BaseModel):
    guestName: Optional[str] = None
    guestPhone: Optional[str] = None
    guestEmail: Optional[str] = None
    customerId: Optional[str] = None
    partySize: Optional[int] = None
    date: Optional[str] = None
    time: Optional[str] = None
    duration: Optional[int] = None
    tableId: Optional[str] = None
    tableNumber: Optional[str] = None
    section: Optional[str] = None
    specialRequests: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    depositRequired: Optional[float] = None
    depositPaid: Optional[bool] = None
    serverId: Optional[str] = None
    noShowFee: Optional[float] = None
    experienceId: Optional[str] = None
    preOrderNotes: Optional[str] = None
    preOrderCompleted: Optional[bool] = None
    overrideReason: Optional[str] = None


class Reservation(BaseModel):
    id: str = ""
    guestName: str
    guestPhone: Optional[str] = None
    guestEmail: Optional[str] = None
    customerId: Optional[str] = None
    partySize: int = 2
    date: str = ""
    time: str = ""
    duration: int = 90
    tableId: Optional[str] = None
    tableNumber: Optional[str] = None
    floorPlanId: Optional[str] = None
    section: Optional[str] = None
    specialRequests: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = []
    status: str = "confirmed"  # confirmed, seated, completed, cancelled, no_show
    depositRequired: float = 0
    depositPaid: bool = False
    noShowFee: float = 0
    serverId: Optional[str] = None
    source: str = "walk_in"
    seatedAt: Optional[str] = None
    completedAt: Optional[str] = None
    cancellationReason: Optional[str] = None
    createdAt: str = ""
    updatedAt: str = ""
    # Large-booking / booking-size-rules — set by services.booking_rules_engine
    # at creation time from the owner's configured size tiers, never taken
    # verbatim from the request. isLargeBooking is "matched a tier other than
    # the base/smallest tier" — what Pulse and staff screens key off of to
    # flag a booking as needing extra attention.
    isLargeBooking: bool = False
    bookingTierId: Optional[str] = None
    bookingTierLabel: Optional[str] = None
    experienceId: Optional[str] = None
    experienceName: Optional[str] = None
    preOrderRequired: bool = False
    preOrderCompleted: bool = False
    preOrderNotes: Optional[str] = None
    approvalRequired: bool = False
    # not_required | pending | approved | rejected
    approvalStatus: str = "not_required"
    approvedBy: Optional[str] = None
    approvedAt: Optional[str] = None
    # Set only when a staff member deliberately overrode a booking-rule
    # violation (see ReservationCreate.overrideReason) — audit-logged
    # separately, this is what makes that override visible on the
    # reservation itself afterward.
    ruleOverrideReason: Optional[str] = None
    ruleOverrideBy: Optional[str] = None
    businessId: Optional[str] = None
    # Snapshotted once at creation from services.cancellation_policy — the
    # cutoff in effect for THIS booking, frozen so a later change to the
    # business's policy never applies retroactively (see
    # is_within_free_cancellation_window). None on a reservation created
    # before this field existed, which falls back to a live policy lookup.
    cancellationCutoffHours: Optional[float] = None
    # Real payment capture behind depositRequired/depositPaid above — see
    # routes/reservations.py's mark_no_show for how this is actually
    # collected/forfeited.
    depositSessionId: Optional[str] = None
    depositForfeited: bool = False
    depositRefunded: bool = False

    @model_validator(mode="before")
    @classmethod
    def _legacy_aliases(cls, data):
        if isinstance(data, dict):
            # Legacy docs may use customerName/customerPhone/phone
            if not data.get("guestName"):
                data["guestName"] = data.get("customerName") or data.get("name") or "Guest"
            if not data.get("guestPhone"):
                data["guestPhone"] = data.get("customerPhone") or data.get("phone")
            if not data.get("guestEmail"):
                data["guestEmail"] = data.get("customerEmail") or data.get("email")
            # Some table-assignment paths (auto-assign, ai-assign, walk-in
            # seating) copy a floor-plan table's own `number` field through
            # verbatim, and that field isn't consistently stored as a
            # string across every floor plan — coerce here rather than
            # crash response_model validation on an otherwise-valid
            # reservation.
            if isinstance(data.get("tableNumber"), (int, float)):
                data["tableNumber"] = str(data["tableNumber"])
        return data

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = f"RES-{str(uuid.uuid4())[:8].upper()}"
        now = datetime.utcnow().isoformat()
        if not self.createdAt:
            self.createdAt = now
        if not self.updatedAt:
            self.updatedAt = now
