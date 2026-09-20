from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
import uuid

class Customer(BaseModel):
    businessId: Optional[str] = None
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: EmailStr
    phone: str
    membershipTier: str = "Bronze"  # Bronze, Silver, Gold, Platinum
    totalSpent: float = 0.0
    visits: int = 0
    joinDate: datetime = Field(default_factory=datetime.utcnow)
    points: int = 0
    # 360 Guest Profile fields
    birthday: Optional[str] = None
    company: Optional[str] = None
    seatingPreference: Optional[str] = None  # indoor, outdoor, bar, window, booth
    dietaryRestrictions: List[str] = []  # gluten-free, vegan, nut allergy, etc.
    allergies: List[str] = []
    favoriteDishes: List[str] = []
    tags: List[str] = []  # VIP, regular, corporate, birthday-month, etc.
    isVip: bool = False
    notes: str = ""
    noShowCount: int = 0
    avgSpendPerVisit: float = 0.0
    lastVisitDate: Optional[str] = None
    feedbackRating: float = 0.0  # average rating 0-5
    feedbackCount: int = 0
    reservationIds: List[str] = []
    storeCredit: float = 0.0

class CustomerCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str
    membershipTier: str = "Bronze"
    birthday: Optional[str] = None
    company: Optional[str] = None
    seatingPreference: Optional[str] = None
    dietaryRestrictions: List[str] = []
    allergies: List[str] = []
    tags: List[str] = []
    isVip: bool = False
    notes: str = ""

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    membershipTier: Optional[str] = None
    birthday: Optional[str] = None
    company: Optional[str] = None
    seatingPreference: Optional[str] = None
    dietaryRestrictions: Optional[List[str]] = None
    allergies: Optional[List[str]] = None
    favoriteDishes: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    isVip: Optional[bool] = None
    notes: Optional[str] = None
