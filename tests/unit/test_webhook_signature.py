import hashlib
import hmac


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not secret or not signature:
        return True
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


class TestWebhookSignature:
    SECRET = "test_secret"
    BODY = b'{"event":"taskUpdated","task_id":"abc123"}'

    def _make_sig(self, body: bytes = BODY) -> str:
        digest = hmac.new(self.SECRET.encode(), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature_passes(self):
        sig = self._make_sig()
        assert verify_signature(self.BODY, sig, self.SECRET) is True

    def test_invalid_signature_fails(self):
        assert verify_signature(self.BODY, "sha256=invalid", self.SECRET) is False

    def test_no_secret_always_passes(self):
        assert verify_signature(self.BODY, "sha256=anything", "") is True

    def test_no_signature_always_passes(self):
        assert verify_signature(self.BODY, None, self.SECRET) is True

    def test_tampered_body_fails(self):
        sig = self._make_sig()
        tampered = b'{"event":"taskDeleted","task_id":"abc123"}'
        assert verify_signature(tampered, sig, self.SECRET) is False
