import asyncio
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.services.report_service import PeriodicReportService


class EmailService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def send_weekly_report(self, space_id: str) -> None:
        recipients = [r.strip() for r in settings.email_recipients.split(",") if r.strip()]
        if not recipients:
            logger.warning("Email worker: EMAIL_RECIPIENTS não configurado — envio cancelado")
            return

        logger.info(f"Email worker: gerando PDFs semanais (PT + EN) para space {space_id}")
        svc = PeriodicReportService(self._db)
        pdf_pt = await svc.generate_weekly_pdf(space_id, lang="pt")
        pdf_en = await svc.generate_weekly_pdf(space_id, lang="en")

        date_label = datetime.utcnow().strftime("%d/%m/%Y")
        date_stamp = datetime.utcnow().strftime("%Y%m%d")

        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"Relatório Semanal — U2 Broadcast Angola — {date_label}"
        msg["From"] = settings.email_from or settings.email_user
        msg["To"] = ", ".join(recipients)

        msg.attach(MIMEText(_build_html(date_label, date_stamp), "html", "utf-8"))

        for pdf_bytes, filename in [
            (pdf_pt, f"relatorio_semanal_{date_stamp}_PT.pdf"),
            (pdf_en, f"weekly_report_{date_stamp}_EN.pdf"),
        ]:
            part = MIMEApplication(pdf_bytes, _subtype="pdf")
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

        await asyncio.to_thread(_send_smtp, msg.as_string(), recipients)
        logger.info(f"Email worker: relatório semanal enviado para {recipients}")


def _send_smtp(raw_message: str, recipients: list[str]) -> None:
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
            logger.error(f"SMTP: falha ao entregar para {addr} — código {code}: {msg}")
    else:
        logger.info(f"SMTP: entregue com sucesso para todos ({len(recipients)}) destinatários")


def _build_html(date_label: str, date_stamp: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px;">
  <tr><td align="center">
  <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
    <tr>
      <td style="background:#1B3A6B;padding:28px 32px;">
        <p style="margin:0;color:#93c5fd;font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;">U2 BROADCAST ANGOLA</p>
        <h1 style="margin:8px 0 0;color:#ffffff;font-size:22px;">Relatório Semanal de Progresso</h1>
        <p style="margin:6px 0 0;color:#bfdbfe;font-size:13px;">Weekly Progress Report</p>
      </td>
    </tr>
    <tr>
      <td style="padding:28px 32px;">
        <p style="margin:0 0 16px;color:#334155;font-size:14px;line-height:1.6;">
          Olá,<br><br>
          Segue em anexo o relatório semanal de acompanhamento dos projetos de instalação de estúdios e sites FM nas províncias de Angola, referente à semana encerrada em <strong>{date_label}</strong>.
        </p>
        <p style="margin:0 0 12px;color:#334155;font-size:14px;">O relatório está disponível em dois idiomas:</p>
        <table cellpadding="0" cellspacing="0" style="margin-bottom:24px;width:100%;">
          <tr>
            <td style="background:#eff6ff;border-left:3px solid #3b82f6;padding:10px 14px;border-radius:0 4px 4px 0;">
              <p style="margin:0;color:#1e40af;font-size:13px;font-weight:bold;">&#128206; relatorio_semanal_{date_stamp}_PT.pdf</p>
              <p style="margin:3px 0 0;color:#64748b;font-size:12px;">Português &mdash; versão completa</p>
            </td>
          </tr>
          <tr><td style="height:8px;"></td></tr>
          <tr>
            <td style="background:#f0fdf4;border-left:3px solid #22c55e;padding:10px 14px;border-radius:0 4px 4px 0;">
              <p style="margin:0;color:#166534;font-size:13px;font-weight:bold;">&#128206; weekly_report_{date_stamp}_EN.pdf</p>
              <p style="margin:3px 0 0;color:#64748b;font-size:12px;">English &mdash; full report</p>
            </td>
          </tr>
        </table>
        <p style="margin:0;color:#94a3b8;font-size:12px;line-height:1.6;">
          Este email é enviado automaticamente todo domingo pelo sistema de gestão de projetos U2 Broadcast Angola.<br>
          <em>This email is sent automatically every Sunday by the U2 Broadcast Angola project management system.</em>
        </p>
      </td>
    </tr>
    <tr>
      <td style="background:#f8fafc;padding:14px 32px;border-top:1px solid #e2e8f0;">
        <p style="margin:0;color:#94a3b8;font-size:11px;text-align:center;">
          U2 Broadcast Angola &nbsp;&middot;&nbsp; Relatório gerado em {date_label} UTC
        </p>
      </td>
    </tr>
  </table>
  </td></tr>
</table>
</body>
</html>"""
