from pydantic import BaseModel
from typing import Optional, List
import uuid
from datetime import datetime, timezone


class DeviceRegister(BaseModel):
    """Submitted by an already-authenticated app on first launch to claim a
    durable identity for the physical device/terminal it's running on."""
    platform: str  # android | ios | windows | web
    deviceName: str
    deviceModel: Optional[str] = None
    osVersion: Optional[str] = None
    appVersion: Optional[str] = None
    terminalId: Optional[str] = None
    locationId: Optional[str] = None
    capabilities: List[str] = []


class Device(BaseModel):
    id: str
    businessId: str
    locationId: Optional[str] = None
    platform: str
    deviceName: str
    deviceModel: Optional[str] = None
    osVersion: Optional[str] = None
    appVersion: Optional[str] = None
    terminalId: Optional[str] = None
    capabilities: List[str] = []
    status: str = "active"  # active | revoked
    registeredBy: str
    registeredByName: Optional[str] = None
    createdAt: str
    lastSeenAt: Optional[str] = None
    revokedAt: Optional[str] = None
    revokedBy: Optional[str] = None

    @staticmethod
    def new(data: DeviceRegister, business_id: str, registered_by: str, registered_by_name: Optional[str]) -> "Device":
        now = datetime.now(timezone.utc).isoformat()
        return Device(
            id=f"DEV-{uuid.uuid4().hex[:12].upper()}",
            businessId=business_id,
            locationId=data.locationId,
            platform=data.platform,
            deviceName=data.deviceName,
            deviceModel=data.deviceModel,
            osVersion=data.osVersion,
            appVersion=data.appVersion,
            terminalId=data.terminalId,
            capabilities=data.capabilities,
            status="active",
            registeredBy=registered_by,
            registeredByName=registered_by_name,
            createdAt=now,
            lastSeenAt=now,
        )
