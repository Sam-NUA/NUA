"""Native renderer CORS is explicit and never a wildcard authorization shortcut."""
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware
from utils.cors import cors_options, NATIVE_APP_ORIGINS


WEB = "https://app.nuapos.com.au"
NATIVE = ",".join(sorted(NATIVE_APP_ORIGINS))


def client(native=""):
    app = FastAPI()

    @app.get("/protected")
    def protected(authorization: str = Header(default="")):
        if authorization != "Bearer fixture-only":
            raise HTTPException(401)
        return {"ok": True}

    app.add_middleware(CORSMiddleware, **cors_options(WEB, native),
                       allow_methods=["*"], allow_headers=["*"])
    return TestClient(app)


def preflight(c, origin):
    return c.options("/protected", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,x-nua-device-id",
    })


@pytest.mark.parametrize("origin", sorted(NATIVE_APP_ORIGINS))
def test_supported_native_origin_requires_explicit_opt_in(origin):
    assert preflight(client(), origin).status_code == 400
    result = preflight(client(NATIVE), origin)
    assert result.status_code == 200
    assert result.headers["access-control-allow-origin"] == origin
    # A successful transport preflight grants no authenticated data access.
    assert client(NATIVE).get("/protected", headers={"Origin": origin}).status_code == 401


@pytest.mark.parametrize("origin", [
    "*", "null", "https://evil.example", "https://localhost.evil.example",
    "https://localhost:444", "http://localhost", "nua://evil",
    "capacitor://evil", "capacitor://localhost/", "nua://app?token=test",
])
def test_native_origin_config_rejects_wildcards_and_unrecognized_shells(origin):
    with pytest.raises(ValueError, match="unsupported native origin"):
        cors_options(WEB, origin)


def test_foreign_origin_remains_denied_when_native_clients_are_enabled():
    c = client(NATIVE)
    for origin in ["https://evil.example", "https://localhost.evil.example",
                   "nua://evil", "null"]:
        result = preflight(c, origin)
        assert result.status_code == 400
        assert "access-control-allow-origin" not in result.headers
    assert preflight(c, WEB).headers["access-control-allow-origin"] == WEB


def test_native_config_keeps_canonical_web_origin_separate():
    options = cors_options(WEB, NATIVE)
    assert options["allow_origins"][0] == WEB
    assert "*" not in options["allow_origins"]
    assert options["allow_credentials"] is True
    assert len(options["allow_origins"]) == len(set(options["allow_origins"]))


def test_native_origin_config_requires_a_canonical_web_configuration():
    with pytest.raises(ValueError, match="FRONTEND_URL is required"):
        cors_options("", NATIVE)
    assert cors_options("") == {"allow_origins": ["*"], "allow_credentials": False}
