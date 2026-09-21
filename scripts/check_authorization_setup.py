"""
Diagnóstico do módulo de Autorização de Serviço: confere no ClickUp e no .env
tudo o que precisa estar no lugar para o fluxo funcionar, e diz o que falta.

Uso:
    python scripts/check_authorization_setup.py
"""
import asyncio
import os
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.config import settings
from src.services.clickup_client import ClickUpClient

OK, FAIL, WARN = "[ OK ]", "[FALTA]", "[ ! ]"

REQUIRED_FIELDS = {
    "Solicitante": ("short_text", "preenchido pelo funcionário"),
    "E-mail": ("email", "sem ele o solicitante não recebe a decisão"),
    "Província": ("drop_down", ""),
    "Site / Estúdio": ("short_text", ""),
    "Equipamento": ("short_text", ""),
    "Tipo de Intervenção": ("drop_down", ""),
    "Motivo": ("text", ""),
    "Data Prevista": ("date", ""),
    "Duração Estimada": ("number", "casado por prefixo — a unidade pode mudar"),
    "Interrompe Transmissão": ("checkbox", ""),
    "Decidido Por": ("short_text", "preenchido pelo backend"),
    "Data da Decisão": ("date", "preenchido pelo backend"),
    "Observações da Decisão": ("text", "preenchido pelo backend"),
}


def _norm(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip().lower()


def line(mark: str, text: str, detail: str = "") -> None:
    print(f"  {mark} {text}" + (f"  — {detail}" if detail else ""))


async def main() -> None:
    space_id = settings.authorization_space_id
    list_id = settings.authorization_list_id
    pending = []

    print("\n=== .env ===")
    checks = [
        (settings.authorization_module_enabled, "AUTHORIZATION_MODULE_ENABLED=true"),
        (bool(space_id), "AUTHORIZATION_SPACE_ID"),
        (bool(list_id), "AUTHORIZATION_LIST_ID"),
        (bool(settings.authorization_approver_email), "AUTHORIZATION_APPROVER_EMAIL"),
        (bool(settings.authorization_public_base_url), "AUTHORIZATION_PUBLIC_BASE_URL"),
        (bool(settings.email_user and settings.email_password), "SMTP (EMAIL_USER/EMAIL_PASSWORD)"),
    ]
    for ok, label in checks:
        line(OK if ok else FAIL, label)
        if not ok:
            pending.append(label)

    if space_id and space_id == settings.clickup_default_space_id:
        line(FAIL, "O space das autorizações é o MESMO do dashboard",
             "as requisições vão contaminar KPIs e relatórios, e o polling tentará enviá-las ao Airbox")
        pending.append("separar o space")

    if not (space_id and list_id):
        print("\nConfigure AUTHORIZATION_SPACE_ID e AUTHORIZATION_LIST_ID para conferir o ClickUp.")
        return

    async with ClickUpClient() as client:
        print("\n=== ClickUp ===")

        space = await client._get(f"/space/{space_id}")
        line(OK, f"Space '{space.get('name')}'")
        if space.get("private"):
            line(WARN, "O space é privado", "quem não tiver acesso não consegue abrir o formulário")
            pending.append("tornar o space visível para a equipe")
        else:
            line(OK, "Space visível para o workspace")

        lst = await client.get_list(list_id)
        line(OK, f"Lista '{lst.get('name')}'")

        # Statuses
        actual = [s["status"] for s in lst.get("statuses", [])]
        expected = [
            settings.authorization_status_pending,
            settings.authorization_status_approved,
            settings.authorization_status_rejected,
        ]
        missing = [e for e in expected if _norm(e) not in {_norm(a) for a in actual}]
        if missing:
            line(FAIL, f"Statuses: {', '.join(actual)}",
                 f"faltam {', '.join(missing)} — sem eles o fluxo não dispara nem grava a decisão")
            pending.append("criar os statuses")
        else:
            line(OK, f"Statuses: {', '.join(actual)}")
            if _norm(actual[0]) != _norm(settings.authorization_status_pending):
                line(WARN, f"O primeiro status é '{actual[0]}'",
                     f"tarefas novas precisam nascer em '{settings.authorization_status_pending}'")
                pending.append("colocar o status inicial em primeiro lugar")

        # Custom fields
        fields = {f["name"]: f for f in await client.get_list_fields(list_id)}
        for name, (ftype, note) in REQUIRED_FIELDS.items():
            match = next((f for f in fields.values() if _norm(f["name"]).startswith(_norm(name))), None)
            if match is None:
                line(FAIL, f"Campo '{name}'", note)
                pending.append(f"criar o campo {name}")
            elif match["type"] != ftype:
                line(WARN, f"Campo '{match['name']}' é '{match['type']}', esperado '{ftype}'", note)
            else:
                line(OK, f"Campo '{match['name']}' ({match['type']})")

        # Form view
        views = await client._get(f"/list/{list_id}/view")
        form = next((v for v in views.get("views", []) if v.get("type") == "form"), None)
        if form is None:
            line(FAIL, "Form view", "crie em + View → Form")
            pending.append("criar o formulário")
        elif not form.get("public"):
            line(WARN, f"Form '{form.get('name')}' não está público",
                 "publique e copie o link para distribuir")
            pending.append("publicar o formulário")
        else:
            line(OK, f"Form '{form.get('name')}' publicado")
            print(f"         link: {form.get('public_url')}")
            line(WARN, "A API não mostra quais campos estão no formulário",
                 "confirme na tela que 'Solicitante' e 'E-mail' estão lá e obrigatórios")

        # Webhook
        hooks = (await client._get(f"/team/{settings.clickup_team_id}/webhook")).get("webhooks", [])
        ours = [w for w in hooks if "/webhooks/autorizacoes" in (w.get("endpoint") or "")]
        if not ours:
            line(FAIL, "Webhook de autorizações",
                 "rode scripts/register_authorization_webhook.py --url https://DOMINIO/webhooks/autorizacoes")
            pending.append("registrar o webhook")
        for w in ours:
            health = (w.get("health") or {}).get("status", "?")
            mark = OK if health in ("active", "?") else WARN
            line(mark, f"Webhook → {w.get('endpoint')}",
                 f"space={w.get('space_id')} events={w.get('events')} health={health}")

    print("\n=== Resumo ===")
    if pending:
        print(f"  {len(pending)} pendência(s):")
        for item in pending:
            print(f"   - {item}")
    else:
        print("  Tudo pronto. O próximo envio do formulário já notifica o gestor.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
