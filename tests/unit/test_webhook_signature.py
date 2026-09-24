import hashlib
import hmac

import pytest

from src.core.webhook_security import verify_clickup_signature

SECRET = "test_secret"
BODY = b'{"event":"taskUpdated","task_id":"abc123"}'


def _sign(body: bytes = BODY, secret: str = SECRET) -> str:
    """Assinatura como o ClickUp envia em X-Signature: digest hex PURO do
    HMAC-SHA256 do corpo, sem prefixo (https://developer.clickup.com/docs/webhooksignature)."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestVerifyClickUpSignature:
    def test_valid_signature_passes(self):
        assert verify_clickup_signature(SECRET, BODY, _sign()) is True

    def test_uppercase_hex_is_accepted(self):
        assert verify_clickup_signature(SECRET, BODY, _sign().upper()) is True

    def test_prefixed_signature_is_rejected(self):
        # "sha256=<hex>" é a convenção do GitHub; o ClickUp nunca manda assim.
        assert verify_clickup_signature(SECRET, BODY, f"sha256={_sign()}") is False

    def test_invalid_signature_fails(self):
        assert verify_clickup_signature(SECRET, BODY, "invalid") is False

    def test_tampered_body_fails(self):
        tampered = b'{"event":"taskDeleted","task_id":"abc123"}'
        assert verify_clickup_signature(SECRET, tampered, _sign()) is False

    def test_signature_made_with_another_secret_fails(self):
        assert verify_clickup_signature(SECRET, BODY, _sign(secret="outro")) is False

    def test_missing_signature_fails_when_secret_is_set(self):
        # Antes o header ausente pulava a verificação, o que anulava o secret.
        assert verify_clickup_signature(SECRET, BODY, None) is False

    def test_empty_signature_fails_when_secret_is_set(self):
        assert verify_clickup_signature(SECRET, BODY, "") is False

    @pytest.mark.parametrize("signature", [None, "", "qualquer-coisa"])
    def test_no_secret_disables_verification(self, signature):
        # Sem secret configurado a verificação fica desligada (uso local/dev).
        assert verify_clickup_signature("", BODY, signature) is True

    def test_non_ascii_signature_fails_without_raising(self):
        # hmac.compare_digest levanta TypeError com str não-ASCII; isso viraria erro 500.
        assert verify_clickup_signature(SECRET, BODY, "assinatura-inválida-ç") is False
