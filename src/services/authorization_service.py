"""Módulo de Autorização de Serviço.

Fluxo: o funcionário envia o Form do ClickUp -> a tarefa nasce em "Solicitado" ->
o webhook chama este serviço, que envia ao gestor um e-mail com dois links de uso
único -> o gestor confirma numa página nossa -> o serviço escreve a decisão de volta
no ClickUp (status, custom fields e comentário) e avisa o solicitante.

Nenhum link decide nada sozinho: o GET só mostra a página; a decisão acontece no
POST. Isso é proposital — clientes de e-mail e antivírus fazem prefetch de links.
"""
import asyncio
import unicodedata
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.models.authorization_models import ACTION_APPROVE, ACTION_REJECT
from src.repositories.authorization_repository import AuthorizationRepository, utcnow
from src.services.authorization_emails import build_decision_email, build_request_email
from src.services.clickup_client import ClickUpClient
from src.services.smtp_sender import send_smtp

FIELD_DECIDED_BY = "Decidido Por"
FIELD_DECISION_DATE = "Data da Decisão"
FIELD_DECISION_NOTE = "Observações da Decisão"

# Campos preenchidos pelo backend — nunca aparecem no resumo enviado ao gestor.
_DECISION_FIELDS = {FIELD_DECIDED_BY, FIELD_DECISION_DATE, FIELD_DECISION_NOTE}

# Ordem de leitura do resumo. O casamento é por PREFIXO normalizado, para o nome
# sobreviver a mudanças de unidade no ClickUp ("Duração Estimada (h)" virou "(min)").
# Campo fora desta lista vai para o fim, em ordem alfabética — um campo novo criado
# no ClickUp aparece sem quebrar nada.
_FIELD_ORDER = [
    "Solicitante",
    "E-mail",
    "Província",
    "Site / Estúdio",
    "Equipamento",
    "Tipo de Intervenção",
    "Data Prevista",
    "Duração Estimada",
    "Interrompe Transmissão",
    "Motivo",
]

# Cache de list_id -> {nome normalizado do campo: field_id}
_FIELD_ID_CACHE: dict[str, dict[str, str]] = {}


class AuthorizationError(Exception):
    """Erro de negócio com mensagem já apresentável ao usuário final."""


def _norm(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip().lower()


# ─── Formatação (funções puras) ──────────────────────────────────────────────

def format_field_value(field: dict) -> str:
    """Converte o `value` bruto de um custom field do ClickUp em texto legível."""
    if "value" not in field or field["value"] in (None, ""):
        return ""
    value = field["value"]
    ftype = field.get("type", "")

    if ftype == "drop_down":
        options = field.get("type_config", {}).get("options", [])
        for opt in options:
            if opt.get("id") == value or opt.get("orderindex") == value:
                return str(opt.get("name", ""))
        return ""

    if ftype == "date":
        try:
            moment = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (TypeError, ValueError):
            return ""
        return moment.strftime("%d/%m/%Y %H:%M")

    if ftype == "checkbox":
        truthy = value if isinstance(value, bool) else str(value).lower() == "true"
        return "Sim" if truthy else "Não"

    if ftype == "users":
        people = value if isinstance(value, list) else [value]
        names = [str(p.get("username") or p.get("email") or "") for p in people if p]
        return ", ".join(n for n in names if n)

    return str(value)


def build_summary(task: dict) -> list[tuple[str, str]]:
    """Pares (campo, valor) preenchidos pelo solicitante, na ordem de leitura.

    O ClickUp devolve os custom fields em ordem alfabética; o gestor precisa ver
    primeiro quem pediu e onde, e só depois o detalhe técnico.
    """
    summary: list[tuple[str, str]] = []
    for field in task.get("custom_fields", []):
        name = field.get("name", "")
        if name in _DECISION_FIELDS:
            continue
        value = format_field_value(field)
        if value:
            summary.append((name, value))

    return sorted(summary, key=lambda item: _order_rank(item[0]))


def _order_rank(name: str) -> tuple[int, str]:
    normalized = _norm(name)
    for index, entry in enumerate(_FIELD_ORDER):
        if normalized.startswith(_norm(entry)):
            return (index, "")
    return (len(_FIELD_ORDER), normalized)


def find_field(task: dict, name: str) -> dict | None:
    """Busca por prefixo normalizado — imune a mudanças de unidade no nome."""
    target = _norm(name)
    for field in task.get("custom_fields", []):
        if _norm(field.get("name", "")).startswith(target):
            return field
    return None


def build_task_name(task: dict) -> str:
    """Nome padronizado da requisição: "<Equipamento> — <Site>".

    O ClickUp não tem template de nome no Form (só a pergunta "Task name", que o
    usuário digita, ou uma Automation que roda DEPOIS do webhook — o e-mail sairia
    com o nome antigo). Nomear aqui mantém o assunto do e-mail e o título da tarefa
    idênticos por construção, sem gastar cota de automação.

    Sem prefixo "Autorização": o assunto do e-mail já começa com isso e a lista
    inteira é de autorizações — repetir só rouba espaço na notificação do celular.
    Cada parte é encurtada porque `Equipamento` é texto livre e o técnico às vezes
    escreve uma frase inteira.

    Devolve "" quando não há material suficiente — aí o nome original é mantido.
    """
    parts = [
        format_field_value(find_field(task, part) or {})
        for part in ("Equipamento", "Site / Estúdio")
    ]
    filled = [_shorten(p.strip()) for p in parts if p.strip()]
    return " — ".join(filled)


def _shorten(text: str, limit: int = 45) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def validate_note(action: str, note: str | None) -> str:
    """Recusa exige motivo; autorização aceita observação opcional."""
    cleaned = (note or "").strip()
    if action == ACTION_REJECT and not cleaned:
        raise AuthorizationError("É obrigatório informar o motivo da recusa.")
    return cleaned


def requester_email(task: dict) -> str:
    """Endereço para o aviso de decisão, em ordem de confiabilidade:

    1. custom field do tipo `email` (o campo "E-mail" do formulário);
    2. campo de texto cujo nome fale de e-mail e cujo valor pareça um endereço;
    3. campo do tipo `users` (formato antigo do "Solicitante");
    4. criador da tarefa — última linha de defesa. Vale pouco quando o Form é
       público e anônimo: aí o criador é quem publicou o formulário, não quem
       preencheu. Por isso o campo "E-mail" no Form é o que realmente importa.
    """
    fields = task.get("custom_fields", [])

    for field in fields:
        if field.get("type") == "email" and field.get("value"):
            return str(field["value"]).strip()

    for field in fields:
        name = _norm(field.get("name", "")).replace("-", "")
        if "email" in name and field.get("value"):
            candidate = str(field["value"]).strip()
            if "@" in candidate:
                return candidate

    for field in fields:
        if field.get("type") != "users" or not field.get("value"):
            continue
        raw = field["value"]
        people = raw if isinstance(raw, list) else [raw]
        for person in people:
            if person and person.get("email"):
                return str(person["email"])

    return str((task.get("creator") or {}).get("email") or "")


# ─── Serviço ─────────────────────────────────────────────────────────────────

class AuthorizationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = AuthorizationRepository(db)

    # -- entrada: webhook taskCreated ----------------------------------------

    async def handle_task_created(self, task_id: str) -> bool:
        """Envia o pedido ao gestor. Retorna True se o e-mail foi disparado."""
        async with ClickUpClient() as client:
            task = await client.get_task(task_id)

        list_id = (task.get("list") or {}).get("id", "")
        if settings.authorization_list_id and list_id != settings.authorization_list_id:
            logger.debug(f"Autorização: tarefa {task_id} fora da lista configurada — ignorada")
            return False

        status = _norm((task.get("status") or {}).get("status", ""))
        if status != _norm(settings.authorization_status_pending):
            logger.debug(f"Autorização: tarefa {task_id} em '{status}' — só notifico o inicial")
            return False

        if await self._repo.has_tokens_for_task(task_id):
            logger.info(f"Autorização: tarefa {task_id} já notificada — nada a fazer")
            return False

        if not settings.authorization_approver_email:
            logger.error("Autorização: AUTHORIZATION_APPROVER_EMAIL não configurado")
            return False

        task_name = await self._normalize_name(task)
        pair = await self._repo.create_pair(
            task_id, task_name, settings.authorization_token_ttl_days
        )

        html = build_request_email(
            task_name=task_name,
            task_url=task.get("url", ""),
            summary=build_summary(task),
            approve_url=self.decision_url(pair[ACTION_APPROVE].token),
            reject_url=self.decision_url(pair[ACTION_REJECT].token),
            ttl_days=settings.authorization_token_ttl_days,
        )
        await self._send(
            subject=f"Autorização de serviço — {task_name}",
            html=html,
            recipients=[settings.authorization_approver_email],
        )
        logger.info(
            f"Autorização: pedido {task_id} enviado a {settings.authorization_approver_email}"
        )
        return True

    async def _normalize_name(self, task: dict) -> str:
        """Renomeia a tarefa para o padrão e devolve o nome final.

        Idempotente: uma tarefa já no padrão não é tocada. Falha no rename não
        interrompe o fluxo — o pedido segue com o nome que veio do ClickUp.
        """
        current = task.get("name", "(sem título)")
        desired = build_task_name(task)
        if not desired or desired == current:
            return current
        try:
            async with ClickUpClient() as client:
                await client.set_task_name(task["id"], desired)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Autorização: não consegui renomear {task['id']}: {exc}")
            return current
        logger.info(f"Autorização: tarefa {task['id']} renomeada para '{desired}'")
        return desired

    # -- página de confirmação (GET, não altera nada) -------------------------

    async def get_decision_context(self, token: str) -> dict:
        row = await self._require_valid_token(token)
        async with ClickUpClient() as client:
            task = await client.get_task(row.task_id)
        return {
            "action": row.action,
            "task_id": row.task_id,
            "task_name": task.get("name", row.task_name),
            "task_url": task.get("url", ""),
            "summary": build_summary(task),
            "token": token,
        }

    # -- decisão (POST) -------------------------------------------------------

    async def apply_decision(self, token: str, note: str | None) -> dict:
        row = await self._require_valid_token(token)
        cleaned = validate_note(row.action, note)
        approved = row.action == ACTION_APPROVE
        status = (
            settings.authorization_status_approved if approved
            else settings.authorization_status_rejected
        )
        decided_by = settings.authorization_approver_name or "Gestor"
        now = utcnow()
        verdict = "AUTORIZADO" if approved else "RECUSADO"

        comment = (
            f"{verdict} por {decided_by} em {now.strftime('%d/%m/%Y %H:%M')} UTC "
            f"(decisão por e-mail)."
        )
        if cleaned:
            comment += f"\nObservações: {cleaned}"

        async with ClickUpClient() as client:
            task = await client.get_task(row.task_id)
            await client.set_task_status(row.task_id, status)
            await self._write_decision_fields(client, task, decided_by, cleaned, now)
            await client.create_comment(row.task_id, comment)

        await self._repo.consume(token, cleaned)

        to = requester_email(task)
        notified = False
        if to:
            notified = await self._send(
                subject=(
                    f"Serviço {'autorizado' if approved else 'recusado'} — "
                    f"{task.get('name', '')}"
                ),
                html=build_decision_email(
                    task_name=task.get("name", ""),
                    task_url=task.get("url", ""),
                    approved=approved,
                    decided_by=decided_by,
                    note=cleaned,
                ),
                recipients=[to],
            )

        logger.info(f"Autorização: tarefa {row.task_id} -> {status} por {decided_by}")
        return {
            "approved": approved,
            "task_name": task.get("name", row.task_name),
            "task_url": task.get("url", ""),
            "note": cleaned,
            "decided_by": decided_by,
            "requester_notified": notified,
        }

    # -- internos -------------------------------------------------------------

    async def _require_valid_token(self, token: str):
        row = await self._repo.get_by_token(token)
        if row is None:
            raise AuthorizationError("Link inválido. Verifique se copiou o endereço completo.")
        if row.used_at is not None:
            raise AuthorizationError("Esta requisição já foi decidida.")
        if row.expires_at < utcnow():
            raise AuthorizationError("Este link expirou. Decida direto no ClickUp.")
        return row

    async def _write_decision_fields(
        self, client: ClickUpClient, task: dict, decided_by: str, note: str, now: datetime
    ) -> None:
        list_id = (task.get("list") or {}).get("id", "")
        if not list_id:
            return
        ids = await self._field_ids(client, list_id)
        epoch_ms = int(now.replace(tzinfo=timezone.utc).timestamp() * 1000)
        values: list[tuple[str, object, dict | None]] = [
            (FIELD_DECIDED_BY, decided_by, None),
            (FIELD_DECISION_DATE, epoch_ms, {"time": True}),
        ]
        if note:
            values.append((FIELD_DECISION_NOTE, note, None))

        for name, value, options in values:
            field_id = ids.get(_norm(name))
            if not field_id:
                logger.warning(f"Autorização: campo '{name}' não existe na lista {list_id}")
                continue
            try:
                await client.set_custom_field(task["id"], field_id, value, options)
            except Exception as exc:  # noqa: BLE001 — a decisão não pode falhar por um campo
                logger.warning(f"Autorização: falha ao gravar '{name}': {exc}")

    async def _field_ids(self, client: ClickUpClient, list_id: str) -> dict[str, str]:
        if list_id not in _FIELD_ID_CACHE:
            fields = await client.get_list_fields(list_id)
            _FIELD_ID_CACHE[list_id] = {_norm(f["name"]): f["id"] for f in fields}
        return _FIELD_ID_CACHE[list_id]

    def decision_url(self, token: str) -> str:
        base = settings.authorization_public_base_url.rstrip("/")
        return f"{base}/autorizacoes/decidir/{token}"

    async def _send(self, subject: str, html: str, recipients: list[str]) -> bool:
        """Retorna True apenas se o e-mail saiu de fato — a página de confirmação
        avisa o gestor quando o solicitante não pôde ser notificado."""
        if not settings.email_user or not settings.email_password:
            logger.error("Autorização: SMTP não configurado — e-mail não enviado")
            return False
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.email_from or settings.email_user
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html, "html", "utf-8"))
        try:
            await asyncio.to_thread(send_smtp, msg.as_string(), recipients)
        except Exception as exc:  # noqa: BLE001 — a decisão já foi gravada no ClickUp
            logger.error(f"Autorização: falha no envio para {recipients}: {exc}")
            return False
        return True
