"""
Notification HTTP surface.
"""
from fastapi import APIRouter, Depends
from deps import get_user
from services import notification_service as ns

router = APIRouter(prefix="/notifications")


@router.get("")
async def my_notifications(unread_only: bool = False, limit: int = 50,
                            user: dict = Depends(get_user)):
    return await ns.list_for(user.get("email"), user.get("role"),
                                unread_only=unread_only, limit=limit,
                                business_id=user.get("businessId"))


@router.get("/unread-count")
async def my_unread_count(user: dict = Depends(get_user)):
    return {"count": await ns.unread_count(user.get("email"), user.get("role"),
                                             business_id=user.get("businessId"))}


@router.post("/{notification_id}/read")
async def read(notification_id: str, user: dict = Depends(get_user)):
    ok = await ns.mark_read(notification_id, user.get("email"))
    return {"read": ok}


@router.post("/read-all")
async def read_all(user: dict = Depends(get_user)):
    n = await ns.mark_all_read(user.get("email"), user.get("role"), business_id=user.get("businessId"))
    return {"marked": n}
