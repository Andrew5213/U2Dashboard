"""Verificação da assinatura dos webhooks do ClickUp (compartilhada pelos dois receptores)."""
import hashlib
import hmac


def verify_clickup_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Valida o header `X-Signature` de um webhook do ClickUp.

    O ClickUp assina o corpo cru com HMAC-SHA256 usando o secret do webhook e envia o
    digest em hexadecimal PURO, sem prefixo `sha256=`
    (https://developer.clickup.com/docs/webhooksignature).

    - Sem secret configurado: verificação desligada (uso local/dev) e retorna True.
    - Com secret: a assinatura é obrigatória; ausente ou diferente retorna False.
    """
    if not secret:
        return True
    if not signature:
        return False

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Compara bytes: compare_digest levanta TypeError com str não-ASCII, o que viraria
    # erro 500 para quem mandar um header malformado.
    return hmac.compare_digest(expected.encode(), signature.strip().lower().encode())
