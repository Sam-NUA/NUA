"""Explicit CORS transport origins for the supported native shells.

This only admits the app's known renderer origins when an operator opts in.
Authentication, device binding and tenant authorization still run normally.
Keep FRONTEND_URL independent: password-recovery links need its HTTPS web origin.
"""

NATIVE_APP_ORIGINS = frozenset({
    "https://localhost",       # Capacitor Android (androidScheme=https)
    "capacitor://localhost",   # Capacitor iOS (iosScheme=capacitor)
    "nua://app",                # Electron's privileged local renderer
})


def cors_options(frontend_url, native_origins=""):
    web_origins = [origin.strip().rstrip("/")
                   for origin in frontend_url.split(",") if origin.strip()]
    native = [origin.strip() for origin in native_origins.split(",") if origin.strip()]
    if any(origin not in NATIVE_APP_ORIGINS for origin in native):
        raise ValueError("NATIVE_APP_CORS_ORIGINS contains an unsupported native origin")
    if native and not web_origins:
        raise ValueError("FRONTEND_URL is required when enabling native app origins")
    if not web_origins:
        # Preserve the existing non-credentialed development fallback.
        return {"allow_origins": ["*"], "allow_credentials": False}
    origins = web_origins + ["http://localhost:3000", "http://127.0.0.1:3000"] + native
    return {"allow_origins": list(dict.fromkeys(origins)), "allow_credentials": True}
