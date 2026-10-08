"""
Social Media Marketing — connect accounts, AI-generate post content from
products/promos/specials, and schedule/publish.

Real cross-posting to Meta/TikTok/X requires per-platform OAuth flows and
business verification. The connect flow here is intentionally MOCKED at
the OAuth boundary so the rest of the product (AI generation, scheduling,
preview, image-library binding) can ship today. Publishing fails explicitly
until a real provider adapter exists; only provider acknowledgement may mark
a post published.
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import uuid
import os
import logging

from database import db
from deps import get_user, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict

router = APIRouter()
logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ("instagram", "facebook", "tiktok", "x", "google_business")
PLATFORM_LABELS = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "tiktok": "TikTok",
    "x": "X (Twitter)",
    "google_business": "Google Business",
}


# ============ MODELS ============
class AccountConnectIn(BaseModel):
    platform: str
    handle: str        # @restaurant_handle
    displayName: Optional[str] = None


class SocialPostIn(BaseModel):
    platform: str                       # which connected account
    postType: str                       # post | story | reel
    caption: str
    hashtags: List[str] = []
    imageUrl: Optional[str] = None      # data: URL from ImageLibrary or http
    sourceType: Optional[str] = None    # product | promotion | special | manual
    sourceId: Optional[str] = None
    scheduledFor: Optional[str] = None  # ISO date string; null = publish-now
    status: Optional[str] = "draft"     # draft | scheduled | published | failed


class AIGenerateIn(BaseModel):
    sourceType: str                    # product | promotion | special
    sourceId: Optional[str] = None     # required for product/promotion
    tone: Optional[str] = "warm"       # warm | bold | playful | luxe | concise
    platforms: List[str] = ["instagram"]
    postType: Optional[str] = "post"   # post | story | reel
    customPrompt: Optional[str] = None
    locale: Optional[str] = "en-AU"


# ============ ACCOUNT CRUD ============
@router.get("/social/accounts")
async def list_accounts(user: dict = Depends(get_user)):
    # Only return rows that match the new schema. Legacy docs from older
    # modules (channel_menus / v25) lived in the same collection and had a
    # different shape — they would render as empty cards in the UI.
    accounts = await db.social_accounts.find(
        {"tokenStatus": {"$exists": True}, **tenant_scope_filter(user.get("businessId"))},
        {"_id": 0},
    ).to_list(50)
    return accounts


@router.post("/social/accounts")
async def connect_account(body: AccountConnectIn, user: dict = Depends(require_owner_or_manager)):
    if body.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(400, f"Platform must be one of {SUPPORTED_PLATFORMS}")
    handle = body.handle.strip().lstrip("@")
    if not handle:
        raise HTTPException(400, "Handle is required")
    existing = await db.social_accounts.find_one(
        {"platform": body.platform, "handle": handle, **tenant_scope_filter(user.get("businessId"))})
    if existing:
        raise HTTPException(409, "This handle is already connected on that platform")
    doc = {
        "id": str(uuid.uuid4()),
        "platform": body.platform,
        "platformLabel": PLATFORM_LABELS[body.platform],
        "handle": handle,
        "displayName": body.displayName or handle,
        # MOCKED — real OAuth tokens go here once the integration ships.
        "tokenStatus": "mock_active",
        "connectedAt": datetime.now(timezone.utc).isoformat(),
        "connectedBy": user.get("email"),
        "businessId": user.get("businessId"),
    }
    await db.social_accounts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/social/accounts/{account_id}")
async def disconnect_account(account_id: str, user: dict = Depends(require_owner_or_manager)):
    guard = await db.social_accounts.find_one({"$and": [{"id": account_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Account not found")
    res = await db.social_accounts.delete_one({"$and": [{"id": account_id}, tenant_scope_filter(user.get("businessId"))]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Account not found")
    return {"deleted": True}


# ============ POSTS ============
@router.get("/social/posts")
async def list_posts(status: Optional[str] = None, platform: Optional[str] = None, user: dict = Depends(get_user)):
    q: dict = tenant_scope_filter(user.get("businessId"))
    if status:
        q["status"] = status
        if status == "published":
            q["publishProvider"] = {"$ne": "stub"}
    if platform:
        q["platform"] = platform
    posts = await db.social_posts.find(q, {"_id": 0}).sort("createdAt", -1).to_list(200)
    for post in posts:
        if post.get("publishProvider") == "stub":
            post["status"] = "simulated"
            post["publishedAt"] = None
    return posts


@router.post("/social/posts")
async def create_post(body: SocialPostIn, user: dict = Depends(require_owner_or_manager)):
    if body.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(400, f"Platform must be one of {SUPPORTED_PLATFORMS}")
    if body.postType not in ("post", "story", "reel"):
        raise HTTPException(400, "postType must be post | story | reel")
    # Constrain status — never trust the caller to mark something already published.
    if body.status and body.status not in ("draft", "scheduled"):
        raise HTTPException(400, "Only draft or scheduled status can be set manually")
    # Must have a connected account for that platform
    if not await db.social_accounts.find_one(
            {"platform": body.platform, **tenant_scope_filter(user.get("businessId"))}):
        raise HTTPException(400, f"No connected {body.platform} account — connect one first")
    doc = {
        "id": str(uuid.uuid4()),
        **body.dict(),
        "status": body.status or "draft",
        "createdBy": user.get("email"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.social_posts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/social/posts/{post_id}/duplicate")
async def duplicate_post(post_id: str, body: Optional[dict] = None, user: dict = Depends(require_owner_or_manager)):
    """Owner-friendly: clone a previous post as a fresh draft (or scheduled
    when `scheduledFor` is provided). Defaults: status='draft', strips
    autoPlan flags, regenerates id + timestamps. Lets the owner reuse a
    high-performing caption without re-running AI.
    """
    body = body or {}
    src = await db.social_posts.find_one({"$and": [{"id": post_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not src or not tenant_owns_strict(src.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Post not found")
    new_status = body.get("status", "draft")
    if new_status not in ("draft", "scheduled"):
        raise HTTPException(400, "duplicate status must be draft | scheduled")
    if new_status == "scheduled" and not body.get("scheduledFor"):
        raise HTTPException(400, "scheduledFor is required when status='scheduled'")
    clone = {
        **src,
        "id": str(uuid.uuid4()),
        "status": new_status,
        "scheduledFor": body.get("scheduledFor") or src.get("scheduledFor"),
        # Strip auto-plan / publish tracking — this is a fresh copy.
        "autoPlan": False,
        "autoPlanRun": False,
        "autoPlanId": None,
        "publishedAt": None,
        "publishProvider": None,
        "duplicatedFrom": post_id,
        "createdBy": user.get("email"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    # Allow lightweight tweaks at duplicate time so the owner can adjust
    # platform / caption / hashtags / image without a second call.
    for key in ("platform", "postType", "caption", "hashtags", "imageUrl"):
        if key in body and body[key] is not None:
            clone[key] = body[key]
    if clone.get("postType") not in ("post", "story", "reel"):
        clone["postType"] = "post"
    if clone.get("platform") not in SUPPORTED_PLATFORMS:
        raise HTTPException(400, f"Platform must be one of {SUPPORTED_PLATFORMS}")
    await db.social_posts.insert_one(clone)
    clone.pop("_id", None)
    return clone


@router.patch("/social/posts/{post_id}")
async def update_post(post_id: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    """Patch an existing post — used by the calendar's drag-to-reschedule
    flow. Only a small, explicit set of fields is mutable; status is
    validated against the same allow-list as create_post."""
    guard = await db.social_posts.find_one({"$and": [{"id": post_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Post not found")
    allowed = {"caption", "hashtags", "imageUrl", "scheduledFor", "status", "postType"}
    update = {k: v for k, v in body.items() if k in allowed}
    if "status" in update and update["status"] not in ("draft", "scheduled"):
        raise HTTPException(400, "Only draft or scheduled status can be set manually")
    if "postType" in update and update["postType"] not in ("post", "story", "reel"):
        raise HTTPException(400, "postType must be post | story | reel")
    if not update:
        raise HTTPException(400, "Nothing to update")
    res = await db.social_posts.update_one({"$and": [{"id": post_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Post not found")
    return await db.social_posts.find_one({"$and": [{"id": post_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})


@router.delete("/social/posts/{post_id}")
async def delete_post(post_id: str, user: dict = Depends(require_owner_or_manager)):
    guard = await db.social_posts.find_one({"$and": [{"id": post_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Post not found")
    res = await db.social_posts.delete_one({"$and": [{"id": post_id}, tenant_scope_filter(user.get("businessId"))]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Post not found")
    return {"deleted": True}


@router.post("/social/posts/{post_id}/publish")
async def publish_post(post_id: str, user: dict = Depends(require_owner_or_manager)):
    """Never claim delivery without a real provider acknowledgement."""
    post = await db.social_posts.find_one({"$and": [{"id": post_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not post or not tenant_owns_strict(post.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Post not found")
    raise HTTPException(
        503, "Publishing is unavailable: this workspace supports content planning only. "
        "Your post has not been sent to the social platform.",
    )


# ============ AI CONTENT GENERATION ============
@router.post("/social/ai-generate")
async def ai_generate(body: AIGenerateIn, user: dict = Depends(require_owner_or_manager)):
    """Generates caption + hashtags + a one-line image alt for a product,
    promotion or general special. Returns ONE generation per platform
    requested. Falls back to a templated copy when the LLM key is missing
    or upstream errors, so the UX never hits a dead end."""
    biz_scope = tenant_scope_filter(user.get("businessId"))
    # 1. Resolve the source content
    subject_label = ""
    subject_detail = ""
    image_hint = None
    if body.sourceType == "product":
        if not body.sourceId:
            raise HTTPException(400, "sourceId is required for product generation")
        p = await db.products.find_one({"id": body.sourceId, **biz_scope}, {"_id": 0})
        if not p:
            raise HTTPException(404, "Product not found")
        subject_label = p.get("name", "our latest dish")
        subject_detail = (
            f"Category: {p.get('category', 'food')}, price ${p.get('price', 0):.2f}. "
            f"Description: {p.get('description') or p.get('seoDescription') or ''}"
        )
        image_hint = p.get("image")
    elif body.sourceType == "promotion":
        if not body.sourceId:
            raise HTTPException(400, "sourceId is required for promotion generation")
        promo = await db.promotions.find_one({"id": body.sourceId, **biz_scope}, {"_id": 0})
        if not promo:
            raise HTTPException(404, "Promotion not found")
        subject_label = promo.get("name", "our latest deal")
        subject_detail = (
            f"{promo.get('discount', 0)}% off — schedule: {promo.get('schedule', 'ongoing')}, "
            f"type: {promo.get('type', 'category')}"
        )
    elif body.sourceType == "special":
        subject_label = (body.customPrompt or "Tonight's special")[:80]
        subject_detail = body.customPrompt or "A short, irresistible food highlight."
    else:
        raise HTTPException(400, "sourceType must be product | promotion | special")

    platforms = [p for p in body.platforms if p in SUPPORTED_PLATFORMS] or ["instagram"]
    results = []
    for platform in platforms:
        gen = await _generate_for_platform(
            platform=platform,
            post_type=body.postType or "post",
            tone=body.tone or "warm",
            subject_label=subject_label,
            subject_detail=subject_detail,
            locale=body.locale or "en-AU",
        )
        gen["platform"] = platform
        gen["sourceType"] = body.sourceType
        gen["sourceId"] = body.sourceId
        if image_hint and not gen.get("imageHint"):
            gen["imageHint"] = image_hint
        results.append(gen)
    return {"generations": results}


def _fallback_generation(platform: str, post_type: str, subject_label: str) -> dict:
    """Template used when the LLM key is unavailable or upstream errors."""
    base_tags = ["#nua", "#restaurant", "#foodie", "#chefspecial"]
    platform_tag = {
        "instagram": "#instafood",
        "facebook": "#facebook",
        "tiktok": "#tiktokfood",
        "x": "#foodtwitter",
        "google_business": "#localfavourite",
    }.get(platform, "#food")
    caption = f"{subject_label} — fresh from our kitchen tonight. Come taste it."
    if post_type == "story":
        caption = f"Tonight only: {subject_label}. Swipe up before it's gone."
    elif post_type == "reel":
        caption = f"30s of {subject_label} pure magic 🎬 (recipe whispered in the comments)."
    return {
        "caption": caption,
        "hashtags": base_tags + [platform_tag],
        "imageAlt": f"A close-up shot of {subject_label}.",
        "isFallback": True,
    }


async def _generate_for_platform(*, platform: str, post_type: str, tone: str,
                                 subject_label: str, subject_detail: str, locale: str) -> dict:
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return _fallback_generation(platform, post_type, subject_label)
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        # NOTE: do NOT stream here — we need a single JSON envelope back.
        system = (
            f"You are a senior restaurant social media editor writing in {locale}. "
            "Output ONLY a single JSON object with keys caption (string), "
            "hashtags (string array, leading # included, no spaces), and imageAlt (string). "
            "No commentary. No markdown fences. "
            "Captions must respect platform norms: Instagram ≤ 220 chars, "
            "TikTok hooky + emoji-friendly, X ≤ 240 chars total incl hashtags, "
            "Facebook conversational, Google Business factual."
        )
        chat = LlmChat(
            api_key=key,
            session_id=f"social-{uuid.uuid4()}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-6")
        prompt = (
            f"Platform: {platform}. Post type: {post_type}. Tone: {tone}.\n"
            f"Subject: {subject_label}\nDetails: {subject_detail}\n"
            "Return JSON now."
        )
        resp = await chat.send_message(UserMessage(text=prompt))
        text = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
        import json
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1] if "```" in cleaned[3:] else cleaned[3:]
            cleaned = cleaned.lstrip("json").strip()
        data = json.loads(cleaned)
        if "caption" not in data or "hashtags" not in data:
            raise ValueError("missing keys")
        data["isFallback"] = False
        return data
    except Exception as exc:
        logger.warning("AI social generation failed (%s) — using fallback", exc)
        out = _fallback_generation(platform, post_type, subject_label)
        out["aiError"] = type(exc).__name__
        return out


@router.get("/social/platforms")
async def list_platforms(_: dict = Depends(get_user)):
    return [
        {"key": k, "label": PLATFORM_LABELS[k]} for k in SUPPORTED_PLATFORMS
    ]


# ============ BEST TIME TO POST (per platform) ============
# Mining POS peak hours per category, then mapping to platform audiences.
# Until real Meta / TikTok / X impression data is available (post-OAuth),
# this is the most honest signal we have: when does this restaurant's
# audience actually spend.
#
# Mapping (refined from category social-engagement heuristics):
#   instagram        → café / breakfast / lunch categories  (10:00 – 13:00 peak)
#   facebook         → all dine-in / dinner categories      (afternoon + dinner)
#   tiktok           → late-night / desserts / drinks       (19:00 – 22:00 peak)
#   x                → coffee / specials / fast-casual      (commute hours)
#   google_business  → general daytime traffic              (lunch window)
PLATFORM_CATEGORY_AFFINITY = {
    "instagram":       ["Coffee", "Breakfast", "Brunch", "Lunch", "Cakes", "Pastry"],
    "facebook":        ["Mains", "Dinner", "Family", "Pasta", "Pizza"],
    "tiktok":          ["Desserts", "Cocktails", "Drinks", "Late Night", "Snacks"],
    "x":               ["Coffee", "Specials", "Fast"],
    "google_business": ["Mains", "Lunch", "Coffee", "Breakfast"],
}
# Per-platform timing safety bands (clamps the result to a "reasonable"
# posting window even when the data is thin):
PLATFORM_TIME_BANDS = {
    "instagram":       (8, 13),
    "facebook":        (12, 20),
    "tiktok":          (18, 22),
    "x":               (7, 11),
    "google_business": (10, 14),
}


@router.get("/social/best-times")
async def best_times(user: dict = Depends(get_user)):
    """Suggest a 'best time to post' (local HH:MM) per platform, derived from
    your own POS peak-hour analytics. Falls back to the platform's safety
    band when the restaurant has no transactions yet.

    Returns:
      [{platform, recommendedHour, recommendedTime, sampleSize, source}]
    """
    return await _compute_best_times(user.get("businessId"))


async def _compute_best_times(business_id: Optional[str] = None) -> list:
    """Internal — same calculation as /social/best-times, callable from
    the AI weekly-plan flow so each platform's posts get scheduled at
    that channel's own optimal hour."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    pipeline = [
        {"$match": {"timestamp": {"$gte": since}, **tenant_scope_filter(business_id)}},
        {"$unwind": "$items"},
        {
            "$group": {
                "_id": {
                    "hour": {"$hour": {"$dateFromString": {"dateString": "$timestamp"}}},
                    "category": "$items.category",
                },
                "qty": {"$sum": "$items.quantity"},
            }
        },
    ]
    try:
        buckets = await db.transactions.aggregate(pipeline).to_list(2000)
    except Exception:
        buckets = []

    out = []
    for platform in SUPPORTED_PLATFORMS:
        affinity = set(PLATFORM_CATEGORY_AFFINITY.get(platform, []))
        hour_qty: dict = {}
        sample = 0
        for b in buckets:
            cat = (b.get("_id", {}).get("category") or "").strip()
            if not cat:
                continue
            matches = any(token.lower() in cat.lower() for token in affinity)
            if not matches:
                continue
            h = b["_id"]["hour"]
            hour_qty[h] = hour_qty.get(h, 0) + b["qty"]
            sample += b["qty"]

        lo, hi = PLATFORM_TIME_BANDS[platform]
        in_band = {h: q for h, q in hour_qty.items() if lo <= h <= hi}
        if in_band:
            best_h = max(in_band.items(), key=lambda kv: kv[1])[0]
            source = "pos_peak"
        elif hour_qty:
            best_h = max(hour_qty.items(), key=lambda kv: kv[1])[0]
            best_h = max(lo, min(hi, best_h))
            source = "pos_peak_clamped"
        else:
            best_h = (lo + hi) // 2
            source = "default_band"
        out.append({
            "platform": platform,
            "platformLabel": PLATFORM_LABELS[platform],
            "recommendedHour": best_h,
            "recommendedTime": f"{best_h:02d}:00",
            "sampleSize": sample,
            "source": source,
            "band": [lo, hi],
        })
    return out


# ============ AI WEEKLY CONTENT PLAN ============
class WeeklyPlanIn(BaseModel):
    daysAhead: int = 7
    postTime: Optional[str] = "12:00"   # local HH:MM the plan should fire each day
    tone: Optional[str] = "warm"
    platforms: Optional[List[str]] = None     # default: every connected platform
    save: bool = True                          # if False, returns a preview without persisting
    # NEW: when true, each platform's scheduled time is auto-selected from
    # POS peak-hour analytics (see `/social/best-times`), giving each channel
    # its own optimal posting time instead of one fixed `postTime` for all.
    useBestTimes: bool = False


@router.post("/social/ai-weekly-plan")
async def ai_weekly_plan(body: WeeklyPlanIn, background_tasks: BackgroundTasks,
                         user: dict = Depends(require_owner_or_manager)):
    """Generate a 7-day cross-platform social plan from top-selling products
    + active promotions, distributed one post per day per platform.

    Source rotation per day:
      - Day 0,3,6 → product (top sellers, cycled)
      - Day 1,4   → promotion (active, cycled)
      - Day 2,5   → 'special' (free-form prompt seeded from the day-of-week)
    Falls back to product → product if no promotions exist.

    The endpoint is idempotent enough to re-run: any prior `auto_plan_*`
    scheduled-but-unpublished post in the target window is dismissed before
    new ones land, so the cashier never ends up with duplicate posts.

    SCALING: when `save=true`, the actual N×P LLM calls are kicked off as
    a FastAPI BackgroundTask so the HTTP response returns in ~30ms. The
    UI polls `GET /social/plan-jobs/{planId}` for progress, or just refreshes
    `GET /social/posts` once the toast fires. Preview mode (`save=false`)
    still runs inline because the caller wants the generated drafts back
    in the response body.
    """
    days = max(1, min(14, body.daysAhead or 7))
    tone = body.tone or "warm"
    try:
        hour, minute = (body.postTime or "12:00").split(":")
        target_hour, target_min = int(hour), int(minute)
    except Exception:
        target_hour, target_min = 12, 0

    # If owner asked for per-platform best times, mine the POS analytics once
    # up front and build a `{platform: hour}` map. Falls back to `postTime`
    # silently when the analytics return nothing useful.
    biz = user.get("businessId")
    best_time_map: dict = {}
    if body.useBestTimes:
        try:
            for row in await _compute_best_times(biz):
                best_time_map[row["platform"]] = int(row["recommendedHour"])
        except Exception as exc:
            logger.warning("best-times computation failed (%s) — falling back to fixed postTime", exc)
            best_time_map = {}

    # 1. Pick the platforms — default to all connected accounts. Be specific
    # about WHY the request fails so the UI can give an actionable nudge.
    connected_accounts = await db.social_accounts.find(
        {"tokenStatus": {"$exists": True}, **tenant_scope_filter(biz)}, {"_id": 0, "platform": 1},
    ).to_list(50)
    connected_keys = sorted({a["platform"] for a in connected_accounts})
    if not connected_keys:
        raise HTTPException(
            400,
            detail={
                "code": "no_connected_accounts",
                "message": "No connected social accounts — connect at least one first.",
                "connected": [], "requested": body.platforms or [],
            },
        )
    if body.platforms:
        requested = [p for p in body.platforms if p in SUPPORTED_PLATFORMS]
        platforms = [p for p in requested if p in connected_keys]
        if not platforms:
            raise HTTPException(
                400,
                detail={
                    "code": "no_matching_platforms",
                    "message": (
                        "None of the requested platforms are connected. "
                        f"Connected: {connected_keys}. Requested: {requested or body.platforms}."
                    ),
                    "connected": connected_keys, "requested": requested or body.platforms,
                },
            )
    else:
        platforms = connected_keys

    # 2. Compute top-selling products (last 7 days). Falls back gracefully
    # when there aren't enough transactions to mine.
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    pipeline = [
        {"$match": {"timestamp": {"$gte": since}, **tenant_scope_filter(biz)}},
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.productId", "qty": {"$sum": "$items.quantity"}}},
        {"$sort": {"qty": -1}}, {"$limit": 7},
    ]
    try:
        top = await db.transactions.aggregate(pipeline).to_list(7)
        top_ids = [t["_id"] for t in top if t.get("_id")]
    except Exception:
        top_ids = []
    if not top_ids:
        fallback = await db.products.find(
            {"eightySixed": {"$ne": True}, **tenant_scope_filter(biz)}, {"_id": 0, "id": 1},
        ).to_list(7)
        top_ids = [p["id"] for p in fallback]
    products_for_plan = []
    for pid in top_ids:
        p = await db.products.find_one({"id": pid, **tenant_scope_filter(biz)}, {"_id": 0})
        if p:
            products_for_plan.append(p)
    if not products_for_plan:
        raise HTTPException(400, "No products available to seed a plan — add a product or run a sale first")

    # 3. Active promotions
    promos = await db.promotions.find({"active": True, **tenant_scope_filter(biz)}, {"_id": 0}).to_list(10)

    # 4. If we're persisting, wipe any leftover auto-plan posts in the upcoming
    # window so re-runs don't pile up duplicates. Preview (save=false) MUST NOT
    # touch persisted state.
    if body.save:
        window_end = (datetime.now(timezone.utc) + timedelta(days=days + 1)).isoformat()
        await db.social_posts.delete_many({
            "autoPlanRun": True,
            "status": "scheduled",
            "scheduledFor": {"$gte": datetime.now(timezone.utc).isoformat(), "$lte": window_end},
            **tenant_scope_filter(biz),
        })

    # 5. Walk N days × P platforms, alternating the source type. The plan-day
    # selection runs synchronously (it's cheap — just dict lookups), then the
    # heavy LLM work is either inlined (preview) or queued (save).
    SPECIAL_SEEDS = [
        "Chef's Choice tonight — limited covers, intimate vibe.",
        "Weekend brunch is on — bring the crew.",
        "Pairing night: every main paired with a hand-picked sip.",
        "Hidden-menu Tuesday — DM us for the secret order.",
    ]
    plan_id = f"plan-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    plan_days = []
    for d in range(days):
        day = now + timedelta(days=d + 1)
        # Anchor day at midnight UTC — the per-platform timing kicks in
        # inside the inner loop so each platform gets its own best hour.
        day_base = day.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        if d % 3 == 1 and promos:
            promo = promos[d % len(promos)]
            plan_days.append({
                "dayBase": day_base,
                "sourceType": "promotion", "sourceId": promo["id"],
                "subjectLabel": promo.get("name", "promo"),
                "subjectDetail": f"{promo.get('discount', 0)}% off — schedule: {promo.get('schedule', 'ongoing')}",
                "imageHint": None,
            })
        elif d % 3 == 2:
            seed = SPECIAL_SEEDS[d % len(SPECIAL_SEEDS)]
            plan_days.append({
                "dayBase": day_base,
                "sourceType": "special", "sourceId": None,
                "subjectLabel": seed[:60], "subjectDetail": seed, "imageHint": None,
            })
        else:
            prod = products_for_plan[d % len(products_for_plan)]
            plan_days.append({
                "dayBase": day_base,
                "sourceType": "product", "sourceId": prod["id"],
                "subjectLabel": prod.get("name", "our top dish"),
                "subjectDetail": (
                    f"Category: {prod.get('category', 'food')}, price ${prod.get('price', 0):.2f}. "
                    f"Description: {prod.get('description') or prod.get('seoDescription') or ''}"
                ),
                "imageHint": prod.get("image"),
            })

    total_posts = len(plan_days) * len(platforms)

    def _resolve_scheduled_for(plan_day: dict, platform: str) -> str:
        """Per-platform scheduling: pick best hour if requested, else the
        fixed `postTime` from the request body. Always returns ISO string."""
        base = datetime.fromisoformat(plan_day["dayBase"])
        hour = best_time_map.get(platform, target_hour) if best_time_map else target_hour
        minute = 0 if best_time_map else target_min
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    if body.save:
        # Persist a job doc so the UI can poll. Then defer the LLM work.
        await db.social_plan_jobs.insert_one({
            "planId": plan_id, "status": "queued", "expected": total_posts, "completed": 0,
            "fallbacks": 0, "platformsUsed": platforms, "tone": tone,
            "useBestTimes": bool(body.useBestTimes),
            "bestTimeMap": best_time_map,
            "createdBy": user.get("email"),
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "businessId": biz,
        })
        background_tasks.add_task(
            _run_weekly_plan_job,
            plan_id=plan_id, plan_days=plan_days, platforms=platforms,
            tone=tone, created_by=user.get("email"),
            best_time_map=best_time_map,
            fallback_hour=target_hour, fallback_minute=target_min,
            business_id=biz,
        )
        return {
            "planId": plan_id,
            "status": "queued",
            "expected": total_posts,
            "platformsUsed": platforms,
            "bestTimeMap": best_time_map,
            "message": f"Generating {total_posts} posts in the background — refresh the calendar in ~{max(5, total_posts * 2)}s.",
        }

    # Preview path — run inline, return the generated drafts directly.
    preview = []
    for plan_day in plan_days:
        for platform in platforms:
            gen = await _generate_for_platform(
                platform=platform, post_type="post", tone=tone,
                subject_label=plan_day["subjectLabel"],
                subject_detail=plan_day["subjectDetail"],
                locale="en-AU",
            )
            preview.append({
                "id": str(uuid.uuid4()),
                "platform": platform, "postType": "post",
                "caption": gen["caption"], "hashtags": gen["hashtags"],
                "imageAlt": gen.get("imageAlt"), "imageUrl": plan_day["imageHint"],
                "sourceType": plan_day["sourceType"], "sourceId": plan_day["sourceId"],
                "scheduledFor": _resolve_scheduled_for(plan_day, platform),
                "status": "preview", "autoPlan": True, "autoPlanRun": False,
                "autoPlanId": plan_id,
                "isFallback": bool(gen.get("isFallback")),
                "createdBy": user.get("email"),
                "createdAt": datetime.now(timezone.utc).isoformat(),
            })

    return {
        "planId": plan_id,
        "saved": 0,
        "preview": preview,
        "posts": preview,
        "platformsUsed": platforms,
        "bestTimeMap": best_time_map,
    }


async def _run_weekly_plan_job(*, plan_id: str, plan_days: list, platforms: list,
                                tone: str, created_by: Optional[str],
                                best_time_map: Optional[dict] = None,
                                fallback_hour: int = 12, fallback_minute: int = 0,
                                business_id: Optional[str] = None):
    """Background worker for `ai-weekly-plan`. Streams progress into
    `social_plan_jobs` so the UI can render a progress bar without holding
    the HTTP connection open. Idempotent against partial failures: each post
    is inserted as it's produced; if the worker crashes mid-flight the
    `status` flips to 'failed' but the partial inserts stay (they're valid
    scheduled posts)."""
    await db.social_plan_jobs.update_one(
        {"planId": plan_id},
        {"$set": {"status": "in_progress", "updatedAt": datetime.now(timezone.utc).isoformat()}},
    )
    completed = 0
    fallbacks = 0
    best_time_map = best_time_map or {}

    def _sched_for(plan_day: dict, platform: str) -> str:
        base = datetime.fromisoformat(plan_day["dayBase"])
        hour = best_time_map.get(platform, fallback_hour) if best_time_map else fallback_hour
        minute = 0 if best_time_map else fallback_minute
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    try:
        for plan_day in plan_days:
            for platform in platforms:
                gen = await _generate_for_platform(
                    platform=platform, post_type="post", tone=tone,
                    subject_label=plan_day["subjectLabel"],
                    subject_detail=plan_day["subjectDetail"],
                    locale="en-AU",
                )
                if gen.get("isFallback"):
                    fallbacks += 1
                doc = {
                    "id": str(uuid.uuid4()),
                    "platform": platform, "postType": "post",
                    "caption": gen["caption"], "hashtags": gen["hashtags"],
                    "imageAlt": gen.get("imageAlt"), "imageUrl": plan_day["imageHint"],
                    "sourceType": plan_day["sourceType"], "sourceId": plan_day["sourceId"],
                    "scheduledFor": _sched_for(plan_day, platform),
                    "status": "scheduled", "autoPlan": True, "autoPlanRun": True,
                    "autoPlanId": plan_id,
                    "isFallback": bool(gen.get("isFallback")),
                    "createdBy": created_by,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "businessId": business_id,
                }
                await db.social_posts.insert_one(doc)
                completed += 1
                # Update job progress every couple of inserts to keep Mongo writes cheap.
                if completed % 2 == 0 or completed == len(plan_days) * len(platforms):
                    await db.social_plan_jobs.update_one(
                        {"planId": plan_id},
                        {"$set": {
                            "completed": completed, "fallbacks": fallbacks,
                            "updatedAt": datetime.now(timezone.utc).isoformat(),
                        }},
                    )
        await db.social_plan_jobs.update_one(
            {"planId": plan_id},
            {"$set": {
                "status": "complete", "completed": completed, "fallbacks": fallbacks,
                "finishedAt": datetime.now(timezone.utc).isoformat(),
            }},
        )
    except Exception as exc:
        logger.exception("Weekly plan worker failed: %s", exc)
        await db.social_plan_jobs.update_one(
            {"planId": plan_id},
            {"$set": {
                "status": "failed", "completed": completed, "fallbacks": fallbacks,
                "error": f"{type(exc).__name__}: {exc}",
                "finishedAt": datetime.now(timezone.utc).isoformat(),
            }},
        )


@router.get("/social/plan-jobs/{plan_id}")
async def get_plan_job(plan_id: str, user: dict = Depends(get_user)):
    """Poll progress for an in-flight or completed weekly plan."""
    job = await db.social_plan_jobs.find_one({"$and": [{"planId": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not job or not tenant_owns_strict(job.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Plan job not found")
    return job
