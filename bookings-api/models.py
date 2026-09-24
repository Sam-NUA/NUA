from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
import uuid


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# ---- Partner (an integrating company; NUA itself is partner "nua-native") ----

class PartnerCreate(BaseModel):
    name: str
    billing_tier: str = "standard"       # standard | growth | enterprise
    branding_mode: str = "co-brand"      # co-brand | white-label
    webhook_url: Optional[str] = None


class Partner(BaseModel):
    id: str = Field(default_factory=lambda: _uid("PTR"))
    name: str
    api_key_hash: str
    test_key_hash: Optional[str] = None
    billing_tier: str = "standard"
    branding_mode: str = "co-brand"
    webhook_url: Optional[str] = None
    created_at: str = ""


# ---- Partner application (self-serve request, before any key exists) ----
# Provisioning a Partner has only ever been possible with the deploy-time
# platform admin key — there was no way for an outside integrator to even
# ask for access without already having the one credential that's supposed
# to be the platform operator's alone. This is the other half: a public,
# unauthenticated way to apply, and an admin-side queue to approve/reject.

class PartnerApplicationCreate(BaseModel):
    company_name: str
    contact_name: str
    contact_email: str
    use_case: str = ""
    website: Optional[str] = None


class PartnerApplication(BaseModel):
    id: str = Field(default_factory=lambda: _uid("APP"))
    company_name: str
    contact_name: str
    contact_email: str
    use_case: str = ""
    website: Optional[str] = None
    status: str = "pending"          # pending | approved | rejected
    partner_id: Optional[str] = None  # set once approved
    rejection_reason: Optional[str] = None
    created_at: str = ""
    resolved_at: Optional[str] = None


# ---- Venue ----

class VenueSettings(BaseModel):
    @field_validator("timezone", check_fields=False)
    @classmethod
    def valid_timezone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use a valid IANA timezone")
        return value

    @field_validator("open_time", "close_time", check_fields=False)
    @classmethod
    def valid_clock(cls, value):
        from datetime import datetime
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError:
            raise ValueError("Use HH:MM opening hours")
        if parsed.strftime("%H:%M") != value:
            raise ValueError("Use HH:MM opening hours")
        return value


class VenueCreate(VenueSettings):
    authority: Literal["platform", "external"] = "platform"
    name: str
    timezone: str = "Australia/Sydney"
    address: str = ""
    open_time: str = "11:00"
    close_time: str = "22:00"
    default_duration_minutes: int = Field(default=90, ge=1, le=10080)


class Venue(VenueSettings):
    authority: Literal["platform", "external"] = "platform"
    id: str = Field(default_factory=lambda: _uid("VEN"))
    partner_id: str
    test: bool = False
    name: str
    timezone: str = "Australia/Sydney"
    address: str = ""
    open_time: str = "11:00"
    close_time: str = "22:00"
    default_duration_minutes: int = Field(default=90, ge=1, le=10080)
    created_at: str = ""


# ---- Resource (a bookable table/room/event space) ----

class ResourceCreate(BaseModel):
    name: str
    capacity_min: int = Field(default=1, ge=1, le=1000)
    capacity_max: int = Field(default=4, ge=1, le=1000)
    type: str = "table"                  # table | room | event_space


class Resource(BaseModel):
    id: str = Field(default_factory=lambda: _uid("RES"))
    venue_id: str
    name: str
    capacity_min: int = Field(default=1, ge=1, le=1000)
    capacity_max: int = Field(default=4, ge=1, le=1000)
    type: str = "table"


# ---- Booking ----

class BookingCreate(BaseModel):
    venue_id: str
    resource_id: Optional[str] = None    # omit to let the engine auto-allocate
    party_size: int = Field(default=2, ge=1, le=1000)
    start_time: str                      # ISO 8601
    end_time: Optional[str] = None       # defaults to start + venue default duration
    contact_name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None


class BookingUpdate(BaseModel):
    resource_id: Optional[str] = None
    party_size: Optional[int] = Field(default=None, ge=1, le=1000)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None         # confirmed | seated | no_show | cancelled


class Booking(BaseModel):
    id: str = Field(default_factory=lambda: _uid("BKG"))
    venue_id: str
    resource_id: Optional[str] = None
    party_size: int = Field(default=2, ge=1, le=1000)
    start_time: str = ""
    end_time: str = ""
    contact_name: str = ""
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    status: str = "confirmed"
    source_partner_id: str = ""
    test: bool = False
    created_at: str = ""
    updated_at: str = ""


# ---- Waitlist ----

class WaitlistCreate(BaseModel):
    venue_id: str
    party_size: int = Field(default=2, ge=1, le=1000)
    contact_name: str
    contact_phone: Optional[str] = None


class WaitlistUpdate(BaseModel):
    status: Optional[str] = None         # waiting | seated | abandoned


class WaitlistEntry(BaseModel):
    id: str = Field(default_factory=lambda: _uid("WTL"))
    venue_id: str
    party_size: int = Field(default=2, ge=1, le=1000)
    contact_name: str = ""
    contact_phone: Optional[str] = None
    status: str = "waiting"
    source_partner_id: str = ""
    test: bool = False
    joined_at: str = ""


class ExternalReservation(BaseModel):
    version: int = Field(ge=1)
    deleted: bool = False
    source_timezone: str = "UTC"
    contact_name: str = "Guest"
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    party_size: int = Field(default=2, ge=1, le=1000)
    date: Optional[str] = None
    time: Optional[str] = None
    duration: int = Field(default=90, ge=1, le=10080)
    status: str = Field(default="confirmed", max_length=40)


class WaitlistSeat(BaseModel):
    start_time: str
    end_time: Optional[str] = None
    resource_id: Optional[str] = None
