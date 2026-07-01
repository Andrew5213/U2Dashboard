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
        week_num = datetime.utcnow().isocalendar()[1]
        year = datetime.utcnow().year
        msg["Subject"] = f"Weekly Progress Report — U2 Broadcast Angola — W{week_num:02d}/{year}"
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
    now = datetime.utcnow()
    week_num = now.isocalendar()[1]
    year = now.year

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Weekly Progress Report — U2 Broadcast Angola</title>
</head>
<body style="margin:0;padding:0;background:#eef2f7;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7;padding:40px 16px;">
  <tr><td align="center">
  <table width="620" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:4px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.12);">

    <!-- TOP ACCENT BAR -->
    <tr>
      <td style="background:#1B3A6B;height:4px;font-size:0;line-height:0;">&nbsp;</td>
    </tr>

    <!-- HEADER -->
    <tr>
      <td style="background:#1B3A6B;padding:32px 40px 28px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <p style="margin:0 0 6px;color:#93c5fd;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;">U2 Broadcast Angola</p>
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;line-height:1.2;">Weekly Progress Report</h1>
              <p style="margin:8px 0 0;color:#bfdbfe;font-size:13px;">Radio Studios &amp; FM Sites Installation Programme</p>
            </td>
            <td align="right" valign="top" style="padding-left:20px;white-space:nowrap;">
              <p style="margin:0;color:#93c5fd;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;">Week</p>
              <p style="margin:4px 0 0;color:#ffffff;font-size:28px;font-weight:700;line-height:1;">{week_num:02d}</p>
              <p style="margin:2px 0 0;color:#bfdbfe;font-size:11px;">{year}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- DIVIDER -->
    <tr>
      <td style="background:#3b82f6;height:2px;font-size:0;line-height:0;">&nbsp;</td>
    </tr>

    <!-- BODY -->
    <tr>
      <td style="padding:36px 40px 28px;">

        <p style="margin:0 0 20px;color:#1e293b;font-size:14px;line-height:1.7;">
          Dear team,
        </p>
        <p style="margin:0 0 20px;color:#334155;font-size:14px;line-height:1.7;">
          Please find attached the weekly progress report for the U2 Broadcast Angola installation programme,
          covering radio studios and FM sites across Angolan provinces.
          This report reflects the project status as of <strong style="color:#1e293b;">{date_label} UTC</strong>.
        </p>
        <p style="margin:0 0 28px;color:#334155;font-size:14px;line-height:1.7;">
          Two versions of the report are enclosed for your reference:
        </p>

        <!-- ATTACHMENT CARDS -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
          <tr>
            <td style="background:#f8fafc;border:1px solid #e2e8f0;border-left:3px solid #1B3A6B;border-radius:0 4px 4px 0;padding:14px 18px;">
              <p style="margin:0;color:#0f172a;font-size:13px;font-weight:700;">weekly_report_{date_stamp}_EN.pdf</p>
              <p style="margin:4px 0 0;color:#64748b;font-size:12px;line-height:1.5;">English &mdash; Full project report including executive summary, project health, overdue tasks, upcoming deadlines and team performance.</p>
            </td>
          </tr>
          <tr><td style="height:10px;"></td></tr>
          <tr>
            <td style="background:#f8fafc;border:1px solid #e2e8f0;border-left:3px solid #64748b;border-radius:0 4px 4px 0;padding:14px 18px;">
              <p style="margin:0;color:#0f172a;font-size:13px;font-weight:700;">relatorio_semanal_{date_stamp}_PT.pdf</p>
              <p style="margin:4px 0 0;color:#64748b;font-size:12px;line-height:1.5;">Portugu&ecirc;s &mdash; Vers&atilde;o completa do relat&oacute;rio com resumo executivo, sa&uacute;de dos projetos, tarefas em atraso, pr&oacute;ximos prazos e desempenho da equipe.</p>
            </td>
          </tr>
        </table>

        <p style="margin:0;color:#334155;font-size:14px;line-height:1.7;">
          Should you have any questions regarding the data presented in this report, please contact the project management team.
        </p>

      </td>
    </tr>

    <!-- SEPARATOR -->
    <tr>
      <td style="padding:0 40px;"><hr style="border:none;border-top:1px solid #e2e8f0;margin:0;"></td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td style="padding:20px 40px 28px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <p style="margin:0;color:#94a3b8;font-size:11px;line-height:1.6;">
                This is an automated message generated by the U2 Broadcast Angola<br>
                Project Management System. Please do not reply to this email.
              </p>
            </td>
            <td align="right" valign="top" style="padding-left:16px;white-space:nowrap;">
              <p style="margin:0;color:#cbd5e1;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;">U2 Broadcast</p>
              <p style="margin:2px 0 0;color:#e2e8f0;font-size:10px;">Angola</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- BOTTOM ACCENT BAR -->
    <tr>
      <td style="background:#1B3A6B;height:3px;font-size:0;line-height:0;">&nbsp;</td>
    </tr>

  </table>
  </td></tr>
</table>
</body>
</html>"""
