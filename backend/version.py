"""Single source of truth for the app/API version strings every platform
reports and the backend can gate on — directive Phase 11. Bumping
MIN_SUPPORTED_APP_VERSION is a deliberate release action (it starts
rejecting older installed clients), not something that happens as a side
effect of any other change, so it lives alone rather than inside
settings/config that gets touched for unrelated reasons.
"""

APP_VERSION = "1.0.0"
API_VERSION = "v1"

# A client below this version gets 426 Upgrade Required instead of being
# served — but only once it actually sends X-App-Version; a client that
# doesn't send the header (every existing web/Android/iOS/Windows build as
# of this pass) is never blocked by this check. Bump this only when there's
# a real, shipped, newer client build to require — not speculatively.
MIN_SUPPORTED_APP_VERSION = "1.0.0"


def parse(version: str) -> tuple:
    """Parses 'x.y.z' into a fixed-length (major, minor, patch) tuple, so
    '1.0' and '1.0.0' compare equal rather than one looking "shorter, so
    older" than the other. Malformed input sorts as (0, 0, 0) — i.e.
    always "too old" — rather than raising, since this runs on every
    request that carries the header and must never 500 a request over a
    client sending garbage."""
    try:
        parts = [int(p) for p in str(version).strip().split(".")]
        parts = (parts + [0, 0, 0])[:3]
        return tuple(parts)
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_supported(client_version: str) -> bool:
    return parse(client_version) >= parse(MIN_SUPPORTED_APP_VERSION)
