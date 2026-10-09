"""Quem pode abrir a app dentro de um iframe (Nextcloud › External sites).

Sem configuração nenhum cabeçalho é enviado e a app pode ser embutida por qualquer
site — o comportamento de sempre. Com `EMBED_ALLOWED_ORIGINS` preenchido, toda
resposta leva `Content-Security-Policy: frame-ancestors 'self' <origens>` e o
navegador recusa o iframe em qualquer outra origem (proteção contra clickjacking).

É um middleware ASGI puro, e não um `BaseHTTPMiddleware`, para não interferir no
streaming do SSE (`/dashboard/stream`)."""
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def frame_ancestors_policy(origins: list[str]) -> str:
    return "frame-ancestors " + " ".join(["'self'", *origins])


class FrameAncestorsMiddleware:
    def __init__(self, app: ASGIApp, origins: list[str]) -> None:
        self._app = app
        self._header = (b"content-security-policy", frame_ancestors_policy(origins).encode("latin-1"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"content-security-policy"]
                message = {**message, "headers": [*headers, self._header]}
            await send(message)

        await self._app(scope, receive, send_with_policy)
