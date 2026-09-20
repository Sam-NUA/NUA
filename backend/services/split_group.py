"""Group coordination for guest bill-split.

Designated "organizer" guest can invite other guests, manage participant list,
and track group status. Useful for family dinners, group outings where one
person organizes the split.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from database import db
import uuid
import secrets


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_split_group(split_id: str, organizer_phone: str) -> Optional[Dict[str, Any]]:
    """Create a group split with organizer.

    Previously created a group document for ANY split_id string with no
    check it corresponded to a real, open split — a typo'd or entirely
    made-up split_id would still succeed, leaving an orphaned
    db.split_groups document with no split to ever attach to. Returns
    None (the caller 404s) when the split doesn't exist or isn't open."""
    split = await db.bill_splits.find_one({"id": split_id, "status": "open"}, {"_id": 0, "id": 1})
    if not split:
        return None
    group = {
        "id": f"GROUP-{str(uuid.uuid4())[:12].upper()}",
        "splitId": split_id,
        "organizerPhone": organizer_phone,
        "participants": [organizer_phone],  # Organizer is first participant
        "invites": {},  # phone -> invite_token
        "status": "open",
        "createdAt": _now(),
    }

    result = await db.split_groups.insert_one(group)
    group.pop("_id", None)
    return group


async def invite_guest(split_id: str, organizer_phone: str, invite_phone: str) -> Dict[str, Any]:
    """Organizer invites another guest to the split."""
    group = await db.split_groups.find_one(
        {"splitId": split_id, "organizerPhone": organizer_phone}
    )
    if not group:
        return {"error": "Group not found or you're not the organizer", "success": False}

    if invite_phone in group.get("participants", []):
        return {"error": "Guest already in group", "success": False}

    if invite_phone in group.get("invites", {}):
        return {"error": "Invite already sent", "success": False}

    # Generate invite token (short-lived, single-use)
    token = secrets.token_urlsafe(16)
    expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    await db.split_groups.update_one(
        {"id": group["id"]},
        {
            "$set": {
                f"invites.{invite_phone}": {
                    "token": token,
                    "sentAt": _now(),
                    "expiresAt": expires,
                    "status": "pending",
                }
            }
        }
    )

    return {
        "success": True,
        "invitePhone": invite_phone,
        "inviteToken": token,
        "expiresAt": expires,
    }


async def accept_invite(split_id: str, guest_phone: str, invite_token: str) -> Dict[str, Any]:
    """Guest accepts an invite to join a group split."""
    group = await db.split_groups.find_one({"splitId": split_id})
    if not group:
        return {"error": "Split group not found", "success": False}

    invite = group.get("invites", {}).get(guest_phone, {})
    if not invite:
        return {"error": "No invite found for this phone", "success": False}

    if invite.get("token") != invite_token:
        return {"error": "Invalid invite token", "success": False}

    expires = invite.get("expiresAt")
    if expires and datetime.fromisoformat(expires) < datetime.now(timezone.utc):
        return {"error": "Invite expired", "success": False}

    # Add to participants and mark invite as accepted
    await db.split_groups.update_one(
        {"id": group["id"]},
        {
            "$push": {"participants": guest_phone},
            "$set": {
                f"invites.{guest_phone}.status": "accepted",
                f"invites.{guest_phone}.acceptedAt": _now(),
            }
        }
    )

    return {
        "success": True,
        "groupId": group["id"],
        "participantCount": len(group.get("participants", [])) + 1,
    }


async def get_group_status(split_id: str) -> Optional[Dict[str, Any]]:
    """Get status of a split group (participants, invites, etc)."""
    group = await db.split_groups.find_one({"splitId": split_id}, {"_id": 0})
    if not group:
        return None

    return {
        "id": group["id"],
        "splitId": group["splitId"],
        "organizerPhone": group.get("organizerPhone"),
        "participants": group.get("participants", []),
        "participantCount": len(group.get("participants", [])),
        "invitesPending": sum(
            1 for inv in group.get("invites", {}).values()
            if inv.get("status") == "pending"
        ),
        "status": group.get("status"),
        "createdAt": group.get("createdAt"),
    }


async def leave_group(split_id: str, guest_phone: str) -> Dict[str, Any]:
    """Guest leaves a group split."""
    group = await db.split_groups.find_one({"splitId": split_id})
    if not group:
        return {"error": "Group not found", "success": False}

    if guest_phone not in group.get("participants", []):
        return {"error": "Not a participant", "success": False}

    # Cannot leave if organizer and others present
    if guest_phone == group.get("organizerPhone"):
        if len(group.get("participants", [])) > 1:
            return {"error": "Organizer cannot leave while others are in group", "success": False}

    await db.split_groups.update_one(
        {"id": group["id"]},
        {"$pull": {"participants": guest_phone}}
    )

    return {"success": True, "leftAt": _now()}


async def sync_group_to_split(split_id: str) -> Dict[str, Any]:
    """Sync group member list to main split document for easy staff reference."""
    group = await db.split_groups.find_one({"splitId": split_id})
    if not group:
        return {"synced": False, "reason": "no_group"}

    await db.bill_splits.update_one(
        {"id": split_id},
        {
            "$set": {
                "groupMode": True,
                "groupId": group["id"],
                "groupParticipants": group.get("participants", []),
                "groupUpdatedAt": _now(),
            }
        }
    )

    return {
        "synced": True,
        "groupId": group["id"],
        "participantCount": len(group.get("participants", [])),
    }
