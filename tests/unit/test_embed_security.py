"""Cabeçalho que limita quem pode embutir a app num iframe (Nextcloud › External sites)."""
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from src.core.config import Settings
from src.core.embed_security import FrameAncestorsMiddleware, frame_ancestors_policy


def _app(origins: list[str] | None) -> TestClient:
    app = FastAPI()
    if origins:
        app.add_middleware(FrameAncestorsMiddleware, origins=origins)

    @app.get("/")
    async def home():
        return {"ok": True}

    @app.get("/stream")
    async def stream():
        async def events():
            yield "data: 1\n\n"
            yield "data: 2\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    return TestClient(app)


def test_policy_lists_self_and_the_configured_origins():
    assert frame_ancestors_policy(["https://cloud.exemplo.com"]) == "frame-ancestors 'self' https://cloud.exemplo.com"


def test_header_is_sent_when_origins_are_configured():
    response = _app(["https://cloud.exemplo.com", "https://nc.outro.org"]).get("/")
    assert response.headers["content-security-policy"] == (
        "frame-ancestors 'self' https://cloud.exemplo.com https://nc.outro.org"
    )


def test_nothing_changes_without_configuration():
    response = _app(None).get("/")
    assert "content-security-policy" not in response.headers
    assert "x-frame-options" not in response.headers


def test_streaming_responses_keep_working_and_carry_the_header():
    response = _app(["https://cloud.exemplo.com"]).get("/stream")
    assert response.text == "data: 1\n\ndata: 2\n\n"
    assert "frame-ancestors" in response.headers["content-security-policy"]


def test_setting_splits_origins_and_drops_the_trailing_slash():
    settings = Settings(embed_allowed_origins=" https://cloud.exemplo.com/ , ,https://nc.outro.org")
    assert settings.embed_origins == ["https://cloud.exemplo.com", "https://nc.outro.org"]
    assert Settings(embed_allowed_origins="").embed_origins == []
