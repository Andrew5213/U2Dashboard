"""Ponte Inspector → ClickUp: regras puras (sem rede nem banco).

O Broadcast Inspector avalia as fotos de cada sala por etapas (ver o projeto Broadcast-Inspector).
Aqui essa leitura vira atualização das tarefas do cronograma no ClickUp:

    sala do Inspector ──(ROOM_LISTS)──► lista do ClickUp (STUDIO, CTP, NEWSROOM, Site FM)
    etapas + fotos   ──(Claude)──────► tarefas-folha da lista com o % que as fotos comprovam

Só o space de laboratório configurado (INSPECTOR_BRIDGE_SPACE_ID) é tocado — a verificação é feita
no serviço, contra o space devolvido pelo próprio ClickUp para a lista.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

# Nome da sala (pasta do Nextcloud / ambiente do Inspector) → nome da lista na pasta da cidade.
DEFAULT_ROOM_LISTS = {
    "Announcer Room": "STUDIO",
    "Control Room": "STUDIO",
    "Studio": "STUDIO",
    "Technical Center": "CTP",
    "CTP": "CTP",
    "Newsroom": "NEWSROOM",
    "Transmission Site": "Site FM",
}

MAX_PHOTOS_TO_MODEL = 6
MAX_PHOTOS_PER_TASK = 4


def norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def room_list_name(room: str, mapping: dict[str, str] | None = None) -> str | None:
    """"Control Room (Sala de Controle Técnico)" → "STUDIO". O nome da sala pode trazer a tradução."""
    mapping = mapping or DEFAULT_ROOM_LISTS
    key = norm(str(room).split("(", 1)[0])
    for room_name, list_name in mapping.items():
        if norm(room_name) == key:
            return list_name
    for room_name, list_name in mapping.items():  # "Studio Control Room 2" etc.
        if norm(room_name) and norm(room_name) in key:
            return list_name
    return None


def match_folder(folders: list[dict], city: str) -> dict | None:
    """Pasta da cidade: "LUBANGO" casa com "LUBANGO"; "CAXITO" com "CAXITO - MABUBAS"."""
    key = norm(city)
    exact = [f for f in folders if norm(f.get("name")) == key]
    if exact:
        return exact[0]
    partial = [f for f in folders if key and (key in norm(f.get("name")) or norm(f.get("name")).split(" ")[0] == key)]
    return partial[0] if len(partial) == 1 else None


def read_progress(task: dict, field_name: str = "% Concluído") -> float:
    for f in task.get("custom_fields") or []:
        if f.get("name") == field_name:
            value = f.get("value")
            if isinstance(value, dict):
                try:
                    return float(value.get("current") or 0)
                except (TypeError, ValueError):
                    return 0.0
            return 0.0
    return 0.0


@dataclass(frozen=True)
class Candidate:
    task_id: str
    path: str          # "Disciplina > Grupo > Tarefa"
    percent: float
    status: str


def leaf_candidates(tasks: list[dict]) -> list[Candidate]:
    """Tarefas-folha da lista, com o caminho até ao topo (o nome sozinho é ambíguo)."""
    by_id = {t["id"]: t for t in tasks}
    parents = {t.get("parent") for t in tasks if t.get("parent")}

    def path(task: dict) -> str:
        names, current, seen = [], task, set()
        while current and current["id"] not in seen:
            seen.add(current["id"])
            names.append(current.get("name", "").strip())
            current = by_id.get(current.get("parent"))
        return " > ".join(reversed(names))

    out = []
    for t in tasks:
        if t["id"] in parents:
            continue
        status = ((t.get("status") or {}).get("status") or "").strip()
        out.append(Candidate(t["id"], path(t), read_progress(t), status))
    return out


SYSTEM_PROMPT = """És o assistente de planeamento de uma obra de radiodifusão em Angola. Recebes a avaliação de uma
inspeção fotográfica de uma sala (feita por outra IA e pela equipa no Broadcast Inspector) e a lista de tarefas do
cronograma dessa sala no ClickUp. O teu trabalho é dizer que tarefas do cronograma essa inspeção comprova e quanto de
cada uma está feito.

Regras:
1. Escolhe só tarefas que as fotos ou o relato comprovam. Na dúvida, não incluas a tarefa: uma tarefa errada no
   cronograma move as datas de tudo o que vem depois.
2. "percentual" é quanto DESSA TAREFA está feito, em múltiplos de 5 (100 = concluída).
3. Nunca proponhas um percentual abaixo do atual da tarefa: o cronograma não regride por uma foto.
4. Uma etapa da inspeção pode corresponder a várias tarefas (ex.: "Piso técnico" → instalação do piso elevado e, se
   visível, o rodapé), e várias etapas podem não ter tarefa correspondente — não forces a correspondência.
5. O relato da equipa é aceite como evidência, inclusive para concluir (fonte "relato"), desde que nenhuma foto o
   contradiga.
6. Distingue o que é novo do que já existia: reforma; o piso cerâmico, visor ou ar condicionado antigos não contam.
7. Uma lista pode cobrir várias salas (ex.: STUDIO = sala de locução + sala de controle). Uma tarefa que, pelo nome,
   vale para todas essas salas só chega a 100% se a inspeção mostrar todas; vendo só uma, dá um percentual proporcional.
   Uma tarefa com o nome de outra sala (ex.: "announcer booth" numa inspeção da sala de controle) não se atualiza.
8. Uma etapa posterior concluída permite deduzir as anteriores da mesma parede/elemento (paredes pintadas → placas e
   estrutura de drywall feitas); diz na evidência que é uma dedução.
9. "evidencia": frase curta, em português, dizendo o que nas fotos/relato sustenta o percentual. Vai para o comentário
   da tarefa, lido pelo gestor.
"""


def rooms_of_list(list_name: str, mapping: dict[str, str] | None = None) -> list[str]:
    mapping = mapping or DEFAULT_ROOM_LISTS
    return [room for room, name in mapping.items() if norm(name) == norm(list_name) and norm(room) != norm(name)]


def build_user_text(payload: dict, candidates: list[Candidate], n_photos: int, list_name: str = "",
                    list_rooms: list[str] | None = None) -> str:
    stages = "\n".join(
        f"- {s.get('name')}: {s.get('status')}, {s.get('percent')}% da etapa"
        f" ({'relato' if s.get('source') == 'relato' else 'foto'}) — {s.get('evidence', '')}"
        for s in payload.get("stages") or []) or "- (nenhuma etapa avaliada)"
    observations = "\n".join(f"- {o}" for o in payload.get("observations") or []) or "- (sem observações)"
    tasks = "\n".join(f"- [{c.task_id}] {c.path} — atual {c.percent:g}% ({c.status or 'sem status'})" for c in candidates)
    coverage = (f"A lista {list_name} do ClickUp cobre estas salas: {', '.join(list_rooms)}. Esta inspeção é só da sala acima.\n"
                if list_rooms and len(list_rooms) > 1 else "")
    return f"""Cidade: {payload.get('city')} · Sala: {payload.get('room')} · Registo de {str(payload.get('recorded_at', ''))[:16]}
{coverage}
Há {n_photos} foto(s) acima, desta inspeção.

RELATO DA EQUIPA: {payload.get('notes') or '(sem relato)'}

AVALIAÇÃO DA INSPEÇÃO POR ETAPAS:
{stages}

O QUE AS FOTOS MOSTRAM (segundo a inspeção):
{observations}

RESUMO DA INSPEÇÃO: {payload.get('summary') or '(sem resumo)'}

TAREFAS DO CRONOGRAMA DESTA SALA ([id] caminho — % atual):
{tasks}

Responde com as tarefas comprovadas por esta inspeção (lista vazia se nenhuma)."""


def response_schema(candidates: list[Candidate]) -> dict:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["atualizacoes", "observacao"],
        "properties": {
            "atualizacoes": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["task_id", "evidencia", "fonte", "percentual"],
                "properties": {
                    "task_id": {"type": "string", "enum": [c.task_id for c in candidates]},
                    "evidencia": {"type": "string"},
                    "fonte": {"type": "string", "enum": ["foto", "relato"]},
                    "percentual": {"type": "integer"},
                },
            }},
            "observacao": {"type": "string"},
        },
    }


@dataclass
class Update:
    task_id: str
    path: str
    before: float
    after: int
    evidence: str
    source: str


@dataclass
class Plan:
    updates: list[Update] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    note: str = ""


def plan_updates(raw: str, candidates: list[Candidate]) -> Plan:
    """Valida a resposta do modelo: tarefa conhecida, % em múltiplos de 5 e nunca abaixo do atual."""
    data = json.loads(raw)
    by_id = {c.task_id: c for c in candidates}
    plan = Plan(note=str(data.get("observacao") or "")[:1000])
    seen: set[str] = set()
    for item in data.get("atualizacoes") or []:
        task = by_id.get(str(item.get("task_id")))
        if not task:
            plan.skipped.append(f"tarefa desconhecida {item.get('task_id')}")
            continue
        if task.task_id in seen:
            continue
        seen.add(task.task_id)
        try:
            pct = int(round(float(item.get("percentual")) / 5.0) * 5)
        except (TypeError, ValueError):
            plan.skipped.append(f"{task.path}: percentual inválido")
            continue
        pct = max(0, min(100, pct))
        if pct <= task.percent:
            plan.skipped.append(f"{task.path}: {pct}% não passa do atual {task.percent:g}%")
            continue
        evidence = str(item.get("evidencia") or "").strip()
        if not evidence:
            plan.skipped.append(f"{task.path}: sem evidência")
            continue
        plan.updates.append(Update(task.task_id, task.path, task.percent, pct, evidence[:600],
                                   "relato" if item.get("fonte") == "relato" else "foto"))
    return plan


def comment_text(update: Update, payload: dict, n_photos: int) -> str:
    when = str(payload.get("recorded_at", ""))[:16].replace("T", " ")
    lines = [
        f"Inspeção fotográfica ({when}) — {payload.get('room')}",
        f"% Concluído: {update.before:g}% → {update.after}% ({'segundo o relato da equipa' if update.source == 'relato' else 'visto nas fotos'})",
        f"Evidência: {update.evidence}",
    ]
    if payload.get("notes"):
        lines.append(f"Relato: {payload['notes']}")
    if n_photos:
        lines.append(f"{n_photos} foto(s) da inspeção em anexo.")
    if payload.get("inspector_url"):
        lines.append(f"Registo no Inspector: {payload['inspector_url']}")
    lines.append("Atualizado automaticamente pela IA do Broadcast Inspector.")
    return "\n".join(lines)
