"""Templates HTML dos e-mails do módulo de Autorização de Serviço.

Tabelas inline e cores fixas: clientes de e-mail não suportam CSS externo
nem variáveis, e o Gmail remove <style> em boa parte dos casos.

Todo texto vindo do ClickUp (preenchido por pessoas) é escapado aqui — é a
única barreira antes de virar HTML.
"""
from html import escape

_NAVY = "#1B3A6B"
_GREEN = "#15803d"
_RED = "#b91c1c"


def _rows(summary: list[tuple[str, str]]) -> str:
    return "".join(
        f"""<tr>
        <td style="padding:10px 0;border-bottom:1px solid #e5e7eb;color:#6b7280;font-size:12px;
                   text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;
                   vertical-align:top;width:170px;">{escape(label)}</td>
        <td style="padding:10px 0 10px 16px;border-bottom:1px solid #e5e7eb;color:#111827;
                   font-size:14px;">{escape(value)}</td>
      </tr>"""
        for label, value in summary
    )


def build_request_email(
    task_name: str,
    task_url: str,
    summary: list[tuple[str, str]],
    approve_url: str,
    reject_url: str,
    ttl_days: int,
) -> str:
    """E-mail enviado ao gestor com os dois botões de decisão."""
    task_name = escape(task_name)
    return f"""<!DOCTYPE html>
<html lang="pt"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#eef2f7;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:4px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.12);">

  <tr><td style="background:{_NAVY};padding:28px 36px;">
    <p style="margin:0 0 6px;color:#93c5fd;font-size:10px;font-weight:700;
              letter-spacing:2px;text-transform:uppercase;">U2 Broadcast Angola</p>
    <h1 style="margin:0;color:#fff;font-size:21px;font-weight:700;line-height:1.3;">
      Pedido de Autorização de Serviço</h1>
  </td></tr>

  <tr><td style="padding:28px 36px 8px;">
    <p style="margin:0 0 4px;color:#6b7280;font-size:12px;text-transform:uppercase;
              letter-spacing:.5px;">Requisição</p>
    <p style="margin:0 0 20px;color:#111827;font-size:17px;font-weight:600;">{task_name}</p>
    <table width="100%" cellpadding="0" cellspacing="0">{_rows(summary)}</table>
  </td></tr>

  <tr><td style="padding:28px 36px 8px;" align="center">
    <table cellpadding="0" cellspacing="0"><tr>
      <td style="padding-right:10px;">
        <a href="{approve_url}"
           style="display:inline-block;background:{_GREEN};color:#fff;text-decoration:none;
                  padding:15px 34px;border-radius:4px;font-size:15px;font-weight:700;">
          AUTORIZAR</a></td>
      <td style="padding-left:10px;">
        <a href="{reject_url}"
           style="display:inline-block;background:{_RED};color:#fff;text-decoration:none;
                  padding:15px 34px;border-radius:4px;font-size:15px;font-weight:700;">
          RECUSAR</a></td>
    </tr></table>
    <p style="margin:16px 0 0;color:#6b7280;font-size:12px;line-height:1.6;">
      Os botões abrem uma página de confirmação — nada é decidido só por abrir o e-mail.<br>
      Este link é de uso único e expira em {ttl_days} dias.</p>
  </td></tr>

  <tr><td style="padding:20px 36px 32px;" align="center">
    <a href="{task_url}" style="color:{_NAVY};font-size:13px;text-decoration:underline;">
      Ver a requisição completa no ClickUp</a></td></tr>

  <tr><td style="background:#f9fafb;border-top:1px solid #e5e7eb;padding:16px 36px;">
    <p style="margin:0;color:#9ca3af;font-size:11px;">
      Mensagem automática do sistema de gestão da U2 Broadcast Angola.</p></td></tr>

</table></td></tr></table></body></html>"""


def build_decision_email(
    task_name: str,
    task_url: str,
    approved: bool,
    decided_by: str,
    note: str,
) -> str:
    """E-mail de retorno ao solicitante depois da decisão."""
    task_name, decided_by, note = escape(task_name), escape(decided_by), escape(note)
    color = _GREEN if approved else _RED
    label = "AUTORIZADO" if approved else "RECUSADO"
    note_block = (
        f"""<tr><td style="padding:0 36px 8px;">
        <p style="margin:0 0 4px;color:#6b7280;font-size:12px;text-transform:uppercase;
                  letter-spacing:.5px;">{'Observações' if approved else 'Motivo da recusa'}</p>
        <p style="margin:0;color:#111827;font-size:14px;line-height:1.6;">{note}</p></td></tr>"""
        if note else ""
    )
    return f"""<!DOCTYPE html>
<html lang="pt"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#eef2f7;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:4px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.12);">

  <tr><td style="background:{color};padding:26px 36px;">
    <p style="margin:0 0 6px;color:rgba(255,255,255,.75);font-size:10px;font-weight:700;
              letter-spacing:2px;text-transform:uppercase;">U2 Broadcast Angola</p>
    <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">Serviço {label}</h1>
  </td></tr>

  <tr><td style="padding:26px 36px 8px;">
    <p style="margin:0 0 4px;color:#6b7280;font-size:12px;text-transform:uppercase;
              letter-spacing:.5px;">Requisição</p>
    <p style="margin:0 0 18px;color:#111827;font-size:17px;font-weight:600;">{task_name}</p>
    <p style="margin:0;color:#374151;font-size:14px;">Decidido por <strong>{decided_by}</strong>.</p>
  </td></tr>
  {note_block}

  <tr><td style="padding:22px 36px 32px;" align="center">
    <a href="{task_url}" style="color:{_NAVY};font-size:13px;text-decoration:underline;">
      Abrir a requisição no ClickUp</a></td></tr>

  <tr><td style="background:#f9fafb;border-top:1px solid #e5e7eb;padding:16px 36px;">
    <p style="margin:0;color:#9ca3af;font-size:11px;">
      Mensagem automática do sistema de gestão da U2 Broadcast Angola.</p></td></tr>

</table></td></tr></table></body></html>"""
