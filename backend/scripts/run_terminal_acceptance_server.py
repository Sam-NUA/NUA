"""Windows CI only: real routes, isolated in-memory database and two venues."""
import os
import uuid
from datetime import datetime, timezone
import run_e2e_server as harness
from database import db
from routes.auth import hash_password


@harness.server.app.on_event("startup")
async def second_test_venue():
    await db.auth_users.insert_one({
        "id": str(uuid.uuid4()), "email": os.environ["NUA_ACCEPTANCE_OTHER_EMAIL"],
        "password_hash": hash_password(os.environ["ADMIN_PASSWORD"]),
        "name": "Other test venue", "role": "owner", "businessId": "acceptance-other-venue",
        "status": "active", "createdAt": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    harness.uvicorn.run(harness.server.app, host="127.0.0.1", port=8123, log_level="warning")
