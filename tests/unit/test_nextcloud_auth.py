"""Identificação pelo JWT do Nextcloud (External sites): assinatura ES256 conferida
só com a chave pública. Os testes fazem o papel do Nextcloud com um par de chaves
gerado na hora."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import auth
from src.core import nextcloud_auth
from src.core.config import settings
from src.core.nextcloud_auth import (
    InvalidNextcloudToken, NextcloudUser, normalize_public_key, verify_token,
)

ISSUER = "https://cloud.exemplo.com"


def _keypair() -> tuple[str, str]:
    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private_pem, public_pem


PRIVATE, PUBLIC = _keypair()
OTHER_PRIVATE, _ = _keypair()


def make_token(private=PRIVATE, algorithm="ES256", **overrides) -> str:
    now = int(time.time())
    payload = {
        "iss": ISSUER, "iat": now, "exp": now + 3600,
        "userdata": {"email": "ana@exemplo.com", "uid": "ana", "displayName": "Ana Paula"},
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, private, algorithm=algorithm)


class TestVerifyToken:
    def test_valid_token_gives_the_user(self):
        user = verify_token(make_token(), PUBLIC)
        assert user == NextcloudUser(uid="ana", email="ana@exemplo.com", display_name="Ana Paula")

    def test_token_signed_by_another_key_is_refused(self):
        with pytest.raises(InvalidNextcloudToken):
            verify_token(make_token(private=OTHER_PRIVATE), PUBLIC)

    def test_tampered_payload_is_refused(self):
        head, _, signature = make_token().split(".")
        forged = jwt.encode(
            {"iss": ISSUER, "iat": int(time.time()), "exp": int(time.time()) + 3600, "userdata": {"uid": "admin"}},
            OTHER_PRIVATE, algorithm="ES256",
        ).split(".")[1]
        with pytest.raises(InvalidNextcloudToken):
            verify_token(f"{head}.{forged}.{signature}", PUBLIC)

    def test_expired_token_is_refused(self):
        past = int(time.time()) - 7200
        with pytest.raises(InvalidNextcloudToken, match="expirado"):
            verify_token(make_token(iat=past, exp=past + 3600), PUBLIC)

    def test_token_without_expiry_is_refused(self):
        with pytest.raises(InvalidNextcloudToken):
            verify_token(make_token(exp=None), PUBLIC)

    def test_only_es256_is_accepted_even_if_the_token_says_otherwise(self):
        # ataque clássico: HS256 "assinado" com a chave pública, que qualquer um tem
        now = int(time.time())
        payload = {"iss": ISSUER, "iat": now, "exp": now + 3600, "userdata": {"uid": "admin"}}
        hs256 = jwt.encode(payload, "x" * 40, algorithm="HS256")
        with pytest.raises(InvalidNextcloudToken):
            verify_token(hs256, PUBLIC)
        unsigned = jwt.encode(payload, None, algorithm="none")
        with pytest.raises(InvalidNextcloudToken):
            verify_token(unsigned, PUBLIC)

    def test_token_without_uid_is_refused(self):
        with pytest.raises(InvalidNextcloudToken, match="utilizador"):
            verify_token(make_token(userdata={"email": "ana@exemplo.com"}), PUBLIC)
        with pytest.raises(InvalidNextcloudToken):
            verify_token(make_token(userdata=None), PUBLIC)

    def test_missing_email_and_name_are_fine(self):
        assert verify_token(make_token(userdata={"uid": "joao"}), PUBLIC) == NextcloudUser(uid="joao")

    def test_issuer_is_checked_only_when_configured(self):
        token = make_token()
        assert verify_token(token, PUBLIC, issuer="").uid == "ana"
        assert verify_token(token, PUBLIC, issuer=ISSUER + "/").uid == "ana"      # a barra final não conta
        with pytest.raises(InvalidNextcloudToken, match="outra instância"):
            verify_token(token, PUBLIC, issuer="https://cloud.outro.org")

    def test_garbage_and_empty_tokens_are_refused(self):
        for bad in ("", None, "abc", "a.b.c"):
            with pytest.raises(InvalidNextcloudToken):
                verify_token(bad, PUBLIC)

    def test_without_a_configured_key_nothing_is_accepted(self):
        with pytest.raises(InvalidNextcloudToken, match="desligada"):
            verify_token(make_token(), "")

    def test_broken_key_in_the_config_does_not_crash(self):
        with pytest.raises(InvalidNextcloudToken):
            verify_token(make_token(), "isto não é uma chave")


class TestPublicKeyFormats:
    def test_key_survives_the_ways_it_can_be_pasted_into_the_env(self):
        one_line = PUBLIC.strip().replace("\n", "\\n")                       # quebras escritas por extenso
        body_only = "".join(PUBLIC.strip().splitlines()[1:-1])               # só o base64
        windows = PUBLIC.replace("\n", "\r\n")
        for variant in (PUBLIC, one_line, f'"{one_line}"', body_only, windows):
            assert normalize_public_key(variant) == PUBLIC
            assert verify_token(make_token(), variant).uid == "ana"

    def test_empty_key_stays_empty(self):
        assert normalize_public_key("") == "" and normalize_public_key(None) == ""


class TestEndpoint:
    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setattr(settings, "nextcloud_jwt_public_key_pem", PUBLIC)
        monkeypatch.setattr(settings, "nextcloud_jwt_issuer", "")
        app = FastAPI()
        app.include_router(auth.router)
        return TestClient(app)

    def test_header_token_identifies_the_user(self, client):
        response = client.get("/auth/me?page=/assistente", headers={"X-Nextcloud-JWT": make_token()})
        assert response.json() == {
            "enabled": True, "authenticated": True,
            "user": {"uid": "ana", "email": "ana@exemplo.com", "display_name": "Ana Paula"},
        }
        assert response.headers["cache-control"] == "no-store"

    def test_query_and_bearer_tokens_work_too(self, client):
        token = make_token()
        assert client.get(f"/auth/me?jwt={token}").json()["authenticated"]
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["authenticated"]

    def test_no_token_or_a_bad_one_is_anonymous_not_an_error(self, client):
        assert client.get("/auth/me").json() == {"enabled": True, "authenticated": False, "user": None}
        bad = client.get("/auth/me", headers={"X-Nextcloud-JWT": make_token(private=OTHER_PRIVATE)})
        assert bad.status_code == 200 and bad.json()["authenticated"] is False

    def test_page_parameter_cannot_inject_log_lines(self, client):
        assert client.get("/auth/me?page=/x%0AINFO forjado", headers={"X-Nextcloud-JWT": make_token()}).status_code == 422

    def test_without_the_key_the_feature_is_off(self, client, monkeypatch):
        monkeypatch.setattr(settings, "nextcloud_jwt_public_key_pem", "")
        response = client.get("/auth/me", headers={"X-Nextcloud-JWT": make_token()})
        assert response.json() == {"enabled": False, "authenticated": False, "user": None}
        assert not nextcloud_auth.is_enabled()
