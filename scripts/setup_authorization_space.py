"""
Cria (de forma idempotente) a estrutura do módulo de Autorização de Serviço no ClickUp:

    Space "Operações U2"  →  Lista "Autorizações de Serviço"  →  Custom Fields

Statuses customizados e Form view NÃO podem ser criados pela API pública do ClickUp —
o script imprime no final o passo a passo manual (leva ~5 minutos na UI).

Uso:
    python scripts/setup_authorization_space.py
    python scripts/setup_authorization_space.py --space-name "Operações U2" --list-name "Autorizações de Serviço"
"""
import argparse
import asyncio
import os
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.config import settings
from src.services.clickup_client import ClickUpClient

DEFAULT_SPACE_NAME = "Operações U2"
DEFAULT_LIST_NAME = "Autorizações de Serviço"

TIPOS_INTERVENCAO = [
    "Manutenção Preventiva",
    "Manutenção Corretiva",
    "Ajuste / Configuração",
    "Substituição de Equipamento",
    "Instalação Nova",
    "Inspeção / Diagnóstico",
]


def _norm(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip().lower()


def _dropdown(options: list[str]) -> dict:
    return {"options": [{"name": name, "orderindex": i} for i, name in enumerate(options)]}


def _field_defs(provincias: list[str]) -> list[dict]:
    """Campos da lista. Os quatro últimos são preenchidos pelo backend, não pelo formulário."""
    return [
        # Texto puro, não `users`: o campo do tipo users rejeita quem não tem acesso
        # ao Space (erro FIELD_129) e não funciona bem em formulário público.
        {"name": "Solicitante", "type": "short_text", "type_config": {}},
        # É daqui que sai o e-mail de retorno ao funcionário — ver requester_email().
        {"name": "E-mail", "type": "email", "type_config": {}},
        {"name": "Província", "type": "drop_down",
         "type_config": _dropdown(provincias + ["Outro"])},
        {"name": "Site / Estúdio", "type": "short_text", "type_config": {}},
        {"name": "Equipamento", "type": "short_text", "type_config": {}},
        {"name": "Tipo de Intervenção", "type": "drop_down", "type_config": _dropdown(TIPOS_INTERVENCAO)},
        {"name": "Motivo", "type": "text", "type_config": {}},
        {"name": "Data Prevista", "type": "date", "type_config": {"include_time": True}},
        {"name": "Duração Estimada (min)", "type": "number", "type_config": {}},
        {"name": "Interrompe Transmissão", "type": "checkbox", "type_config": {}},
        # Preenchidos pelo backend quando o chefe decide:
        {"name": "Decidido Por", "type": "short_text", "type_config": {}},
        {"name": "Data da Decisão", "type": "date", "type_config": {"include_time": True}},
        {"name": "Observações da Decisão", "type": "text", "type_config": {}},
    ]


async def _ensure_space(client: ClickUpClient, name: str) -> dict:
    spaces = await client.get_spaces(settings.clickup_team_id)
    for space in spaces:
        if _norm(space.get("name", "")) == _norm(name):
            print(f"  Space já existe: {space['name']} (id={space['id']})")
            return space
    space = await client.create_space(settings.clickup_team_id, name)
    print(f"  Space criado: {name} (id={space['id']})")
    return space


async def _ensure_list(client: ClickUpClient, space_id: str, name: str) -> dict:
    lists = await client.get_folderless_lists(space_id)
    for lst in lists:
        if _norm(lst.get("name", "")) == _norm(name):
            print(f"  Lista já existe: {lst['name']} (id={lst['id']})")
            return lst
    lst = await client.create_list(space_id, name)
    print(f"  Lista criada: {name} (id={lst['id']})")
    return lst


async def _provincias(client: ClickUpClient) -> list[str]:
    """Nomes dos folders (províncias) do space principal, para popular o dropdown."""
    if not settings.clickup_default_space_id:
        return []
    try:
        folders = await client.get_folders(settings.clickup_default_space_id)
        return [f["name"] for f in folders]
    except Exception as exc:  # noqa: BLE001
        print(f"  ! Não foi possível ler as províncias do space principal: {exc}")
        return []


async def main(space_name: str, list_name: str) -> None:
    async with ClickUpClient() as client:
        print("→ Space")
        space = await _ensure_space(client, space_name)

        print("→ Lista")
        lst = await _ensure_list(client, space["id"], list_name)

        print("→ Províncias (para o dropdown)")
        provincias = await _provincias(client)
        print(f"  {len(provincias)} província(s): {', '.join(provincias) or '(nenhuma)'}")

        print("→ Custom fields")
        existing = await client.get_list_fields(lst["id"])
        existing_names = {_norm(f["name"]) for f in existing}

        for definition in _field_defs(provincias):
            if _norm(definition["name"]) in existing_names:
                print(f"  = {definition['name']} (já existe)")
                continue
            try:
                await client.create_custom_field(lst["id"], definition)
                print(f"  + {definition['name']}")
            except Exception as exc:  # noqa: BLE001
                print(f"  ! Falha ao criar '{definition['name']}': {exc}")

        fields = await client.get_list_fields(lst["id"])

    print("\n" + "=" * 70)
    print("VARIÁVEIS PARA O .env")
    print("=" * 70)
    print(f"AUTHORIZATION_MODULE_ENABLED=true")
    print(f"AUTHORIZATION_SPACE_ID={space['id']}")
    print(f"AUTHORIZATION_LIST_ID={lst['id']}")
    print("\nCampos criados (o backend resolve por nome, não precisa colar os ids):")
    for f in fields:
        print(f"  {f['name']:<28} {f['type']:<12} {f['id']}")

    print("\n" + "=" * 70)
    print("PASSOS MANUAIS NO CLICKUP (a API pública não cobre estes dois)")
    print("=" * 70)
    print(f"""
1) STATUSES da lista "{list_name}"
   Abra a lista → ⋯ → Statuses → Customize → e deixe exatamente:
       Solicitado          (not started)   ← status inicial, é o que dispara o e-mail
       Autorizado          (done)
       Recusado            (closed)
   Os nomes precisam bater com os do .env (AUTHORIZATION_STATUS_*).
   Três statuses bastam: o ClickUp só exige um "not started" e um "closed".

2) FORM VIEW
   Na lista → + View → Form → adicione os campos nesta ordem:
       Solicitante *, E-mail *, Província *, Site / Estúdio *, Equipamento *,
       Tipo de Intervenção *, Motivo *, Data Prevista *,
       Duração Estimada (min), Interrompe Transmissão
   NÃO inclua: Decidido Por, Data da Decisão, Observações da Decisão.
   REMOVA a pergunta "Task name" do formulário: o backend renomeia a tarefa para
   "<Equipamento> — <Site>" ao processar o webhook (o ClickUp não tem template de
   nome no Form, e uma Automation de rename rodaria depois do e-mail já ter saído).
   Copie o link público do formulário e distribua à equipe.

3) WEBHOOK
   python scripts/register_authorization_webhook.py --url https://SEU-DOMINIO/webhooks/autorizacoes
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-name", default=DEFAULT_SPACE_NAME)
    parser.add_argument("--list-name", default=DEFAULT_LIST_NAME)
    args = parser.parse_args()
    asyncio.run(main(args.space_name, args.list_name))
