from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid


class FeedbackCreate(BaseModel):
    customerId: Optional[str] = None
    reservationId: Optional[str] = None
    guestName: str = ""
    rating: int = 5  # 1-5
    foodRating: Optional[int] = None
    serviceRating: Optional[int] = None
    ambienceRating: Optional[int] = None
    comment: Optional[str] = None
    tags: List[str] = []  # great-food, slow-service, etc.


class Feedback(BaseModel):
    businessId: Optional[str] = None
    id: str = ""
    customerId: Optional[str] = None
    reservationId: Optional[str] = None
    guestName: str = ""
    rating: int = 5
    foodRating: Optional[int] = None
    serviceRating: Optional[int] = None
    ambienceRating: Optional[int] = None
    comment: Optional[str] = None
    tags: List[str] = []
    status: str = "new"  # new, read, responded
    response: Optional[str] = None
    createdAt: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = f"FB-{str(uuid.uuid4())[:8].upper()}"
        if not self.createdAt:
            self.createdAt = datetime.utcnow().isoformat()
