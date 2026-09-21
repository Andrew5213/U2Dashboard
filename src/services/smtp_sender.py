"""Envio SMTP compartilhado entre os módulos que mandam e-mail
(relatório semanal e autorizações de serviço)."""
import smtplib

from src.core.config import settings
from src.core.logging import logger


def send_smtp(raw_message: str, recipients: list[str]) -> None:
    """Envia uma mensagem MIME já serializada. Bloqueante — chame via asyncio.to_thread."""
    sender = settings.email_from or settings.email_user
    logger.debug(f"SMTP: conectando {settings.email_smtp_host}:{settings.email_smtp_port}")
    logger.debug(f"SMTP: remetente={sender}, destinatários={recipients}")

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(settings.email_user, settings.email_password)
        failed = server.sendmail(sender, recipients, raw_message)

    if failed:
        for addr, (code, msg) in failed.items():
            detail = msg.decode("utf-8", "replace") if isinstance(msg, bytes) else msg
            logger.error(f"SMTP: falha ao entregar para {addr} — código {code}: {detail}")
    else:
        logger.info(f"SMTP: entregue com sucesso para todos ({len(recipients)}) destinatários")
