"""Quem está a ver a app dentro do Nextcloud.

O app External sites troca o `{jwt}` da URL configurada por um token assinado pela
instância (ES256, válido por 1 hora) com `userdata: {uid, email, displayName}`. Aqui
só se confere a assinatura com a chave **pública** do Nextcloud — não há segredo
partilhado, e a chave pública não serve para forjar um token.

Isto identifica o utilizador, e mais nada: não há sessão nem permissões. Sem a chave
configurada (`NEXTCLOUD_JWT_PUBLIC_KEY_PEM`) a verificação fica desligada e todo
token é ignorado.

A chave sai do Nextcloud, uma por instância (dev e produção têm pares diferentes):
    occ config:app:get external jwt_token_pubkey_es256
O valor só existe depois de alguém abrir o site externo uma vez — o par é gerado na
emissão do primeiro token."""
from dataclasses import asdict, dataclass

import jwt
from fastapi import Request

from src.core.config import settings
from src.core.logging import logger

ALGORITHM = "ES256"
_LEEWAY_SECONDS = 30    # relógios do Nextcloud e desta app nunca batem ao segundo
_PEM_HEADER = "-----BEGIN PUBLIC KEY-----"
_PEM_FOOTER = "-----END PUBLIC KEY-----"


@dataclass(frozen=True)
class NextcloudUser:
    uid: str
    email: str | None = None
    display_name: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class InvalidNextcloudToken(Exception):
    """Token ausente, adulterado, expirado ou de outra instância."""


def normalize_public_key(raw: str | None) -> str:
    """Chave pública em PEM, venha como vier da variável de ambiente: com as quebras
    de linha reais, com `\\n` escrito por extenso (o que cabe numa linha de `.env`)
    ou só o miolo em base64, sem o cabeçalho."""
    text = (raw or "").strip().strip('"').strip("'").replace("\\n", "\n").replace("\r", "").strip()
    if not text:
        return ""
    if _PEM_HEADER in text:
        body = text.split(_PEM_HEADER, 1)[1].split(_PEM_FOOTER, 1)[0]
    else:
        body = text
    body = "".join(body.split())
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "\n".join([_PEM_HEADER, *lines, _PEM_FOOTER]) + "\n"


def is_enabled() -> bool:
    return bool(normalize_public_key(settings.nextcloud_jwt_public_key_pem))


def verify_token(token: str | None, public_key: str | None = None, issuer: str | None = None) -> NextcloudUser:
    """Confere assinatura, validade e (se configurado) o emissor; devolve o utilizador.

    `algorithms` é fixo em ES256: aceitar o algoritmo que o próprio token declara
    permitiria um token HS256 "assinado" com a chave pública, que todos conhecem."""
    key = normalize_public_key(public_key if public_key is not None else settings.nextcloud_jwt_public_key_pem)
    if not key:
        raise InvalidNextcloudToken("verificação desligada: chave pública do Nextcloud não configurada")
    if not token:
        raise InvalidNextcloudToken("token ausente")
    try:
        payload = jwt.decode(
            token, key, algorithms=[ALGORITHM], leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidNextcloudToken("token expirado") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidNextcloudToken(f"token inválido ({type(exc).__name__})") from exc
    except (ValueError, TypeError) as exc:      # chave pública mal formada na configuração
        raise InvalidNextcloudToken(f"chave pública inválida ({exc})") from exc

    expected = (issuer if issuer is not None else settings.nextcloud_jwt_issuer).strip().rstrip("/")
    if expected and str(payload.get("iss") or "").rstrip("/") != expected:
        raise InvalidNextcloudToken("token emitido por outra instância do Nextcloud")

    userdata = payload.get("userdata")
    uid = str(userdata.get("uid") or "").strip() if isinstance(userdata, dict) else ""
    if not uid:
        raise InvalidNextcloudToken("token sem utilizador (userdata.uid)")
    return NextcloudUser(
        uid=uid,
        email=(str(userdata.get("email")).strip() or None) if userdata.get("email") else None,
        display_name=(str(userdata.get("displayName")).strip() or None) if userdata.get("displayName") else None,
    )


def token_from_request(request: Request) -> str | None:
    """O token chega em `?jwt=` (a URL do External sites) ou, nas chamadas feitas pela
    própria página, em `X-Nextcloud-JWT` / `Authorization: Bearer`."""
    token = request.query_params.get("jwt") or request.headers.get("x-nextcloud-jwt")
    if token:
        return token
    authorization = request.headers.get("authorization", "")
    return authorization[7:].strip() or None if authorization.lower().startswith("bearer ") else None


def nextcloud_user(request: Request) -> NextcloudUser | None:
    """Dependência do FastAPI: o utilizador do Nextcloud, ou None quando não há token
    válido. Nunca bloqueia a requisição — identificar não é autorizar."""
    if not is_enabled():
        return None
    token = token_from_request(request)
    if not token:
        return None
    try:
        return verify_token(token)
    except InvalidNextcloudToken as exc:
        # o token em si nunca vai para o log
        logger.warning(f"Nextcloud: token recusado em {request.url.path} — {exc}")
        return None
