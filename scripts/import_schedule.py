"""Importa as planilhas de cronograma de uma província para uma lista do ClickUp.

Cria a estrutura em três níveis (disciplina → grupo → tarefa) com duração,
calendário, % concluído, equipe e dependências. Os "marcos externos" entre
ficheiros viram dependências normais. As datas não são gravadas aqui: quem
calcula e grava é o motor (ScheduleService), que pode ser chamado no fim com
--recalculate.

Sem --yes roda em modo de ensaio (não escreve nada no ClickUp).

Exemplos:
    python scripts/import_schedule.py civil.xlsx logistica.xlsx tecnica.xlsx --list-id 123
    python scripts/import_schedule.py *.xlsx --folder-id 456 --list-name "Site FM" --yes
    python scripts/import_schedule.py *.xlsx --list-id 123 --replace "Site FM" --recalculate --yes
"""
import argparse
import asyncio
import dataclasses
import re
from datetime import datetime
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.database import AsyncSessionLocal, init_db  # noqa: E402
from src.services.clickup_client import ClickUpClient  # noqa: E402
from src.services.schedule_engine import reconcile_leaf  # noqa: E402
from src.services.schedule_fields import (  # noqa: E402
    FIELD_CALENDAR,
    FIELD_COMPLETION,
    FIELD_DEFS,
    FIELD_DURATION,
    FIELD_PERCENT,
    calendar_option_id,
    date_to_ms,
    find_field,
    ms_to_date,
    norm,
    parse_weekend_mask,
)
from src.services.schedule_service import ScheduleService, rate_limit_wait, status_names  # noqa: E402
from src.services.schedule_xlsx import XlsxSchedule, load_schedule  # noqa: E402
import src.models.schedule_models  # noqa: E402,F401

PAUSE_SECONDS = 0.3
_WEEKDAY_NAMES = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


async def call(factory, attempts: int = 6, idempotent: bool = True):
    """`idempotent=False` para criações: uma falha de rede depois de o ClickUp já ter
    criado o item não pode ser repetida às cegas, senão duplica."""
    for attempt in range(1, attempts + 1):
        try:
            result = await factory()
            await asyncio.sleep(PAUSE_SECONDS)
            return result
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 or attempt == attempts:
                raise
            await asyncio.sleep(rate_limit_wait(exc.response))
        except httpx.TransportError:
            if not idempotent or attempt == attempts:
                raise
            await asyncio.sleep(3 * attempt)


def _team_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(name))


def describe(schedule: XlsxSchedule) -> None:
    leaves = [t for t in schedule.tasks if not t.is_summary]
    print(f"Província: {schedule.province} | Projeto: {schedule.project}")
    start = schedule.start.strftime("%d/%m/%Y") if schedule.start else "em branco"
    print(f"Início: {start} | Folga (Seg→Dom): {schedule.weekend_mask} | Feriados: {len(schedule.holidays)}")
    print(f"Linhas: {len(schedule.tasks)} ({len(schedule.tasks) - len(leaves)} resumos, {len(leaves)} tarefas)")
    print(f"Dependências: {sum(len(t.predecessors) for t in schedule.tasks)}")
    print(f"Equipes: {sorted({r for t in schedule.tasks for r in t.resources})}")
    for task in schedule.tasks:
        if task.level <= 2:
            print(f"  {'    ' * (task.level - 1)}{task.name}")


async def ensure_fields(clickup: ClickUpClient, list_id: str) -> list[dict]:
    fields = await call(lambda: clickup.get_list_fields(list_id))
    for definition in FIELD_DEFS:
        if not find_field(fields, definition["name"], definition["type"]):
            await call(lambda d=definition: clickup.create_custom_field(list_id, d), idempotent=False)
            print(f'  campo criado: {definition["name"]}')
    return await call(lambda: clickup.get_list_fields(list_id))


async def configure_list(clickup: ClickUpClient, lst: dict, schedule: XlsxSchedule) -> None:
    payload: dict = {}
    if schedule.start and ms_to_date(lst.get("start_date")) != schedule.start:
        payload.update({"start_date": date_to_ms(schedule.start), "start_date_time": False})
    content = lst.get("content") or ""
    if parse_weekend_mask(content, "") != schedule.weekend_mask:
        days = ", ".join(_WEEKDAY_NAMES[i] for i, flag in enumerate(schedule.weekend_mask) if flag == "1")
        payload["content"] = (content + "\n" if content else "") + f"folga={days}"
    if payload:
        await call(lambda: clickup.update_list(lst["id"], payload))
        start = f"{schedule.start:%d/%m/%Y}" if schedule.start else "em branco"
        print(f"  lista configurada: início {start}, folga {schedule.weekend_mask}")


async def ensure_views(clickup: ClickUpClient, list_id: str, fields: list[dict]) -> list[str]:
    """Cria as vistas "Cronograma" (lista com as colunas do cronograma, subtarefas
    abertas) e "Gantt". Os campos criados pela API não entram sozinhos em nenhuma
    vista — sem isto a lista parece vazia."""
    existing = await call(lambda: clickup._get(f"/list/{list_id}/view"))
    names = {view["name"] for view in existing.get("views", [])}
    custom = [
        find_field(fields, FIELD_DURATION, "number"),
        find_field(fields, FIELD_PERCENT, "manual_progress"),
        find_field(fields, FIELD_CALENDAR, "drop_down"),
    ]
    completion = find_field(fields, FIELD_COMPLETION, "date")
    columns = (
        ["assignee", "startDate", "dueDate"]
        + [f"cf_{f['id']}" for f in custom if f]
        + ["dependencies"]
        + ([f"cf_{completion['id']}"] if completion else [])
    )
    base = {
        "grouping": {"field": "none", "dir": 1, "collapsed": [], "ignore": False},
        "divide": {"field": None, "dir": None, "collapsed": []},
        "sorting": {"fields": []},
        "filters": {"op": "AND", "fields": [], "search": "", "show_closed": True},
        "settings": {"show_subtasks": 2, "show_closed_subtasks": True, "show_assignees": True},
    }
    created = []
    if "Cronograma" not in names:
        view = {**base, "name": "Cronograma", "type": "list", "columns": {"fields": [
            {"field": field, "idx": index, "width": 160, "hidden": False} for index, field in enumerate(columns)
        ]}}
        await call(lambda: clickup._post(f"/list/{list_id}/view", view), idempotent=False)
        created.append("Cronograma")
    if "Gantt" not in names:
        await call(lambda: clickup._post(f"/list/{list_id}/view", {**base, "name": "Gantt", "type": "gantt"}), idempotent=False)
        created.append("Gantt")
    return created


async def delete_existing(clickup: ClickUpClient, list_id: str) -> int:
    tasks = await call(lambda: clickup.get_tasks(list_id, include_closed=True))
    ids = {t["id"] for t in tasks}
    top_level = [t for t in tasks if t.get("parent") not in ids]
    for task in top_level:   # apagar a tarefa de topo apaga as subtarefas
        try:
            await call(lambda t=task: clickup.delete_task(t["id"]))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
    return len(tasks)


async def create_tasks(clickup: ClickUpClient, lst: dict, fields: list[dict], schedule: XlsxSchedule) -> dict[str, str]:
    f_duration = find_field(fields, FIELD_DURATION, "number")
    f_percent = find_field(fields, FIELD_PERCENT, "manual_progress")
    f_calendar = find_field(fields, FIELD_CALENDAR, "drop_down")
    names = status_names(lst.get("statuses"))
    groups = {_team_key(g["name"]): g["id"] for g in await call(clickup.get_groups)}
    # O ClickUp preenche sozinho com a 1ª opção qualquer dropdown omitido na criação
    # (foi assim que "Disciplinas" virou "CIVIL" em tudo). Mandar null explícito evita.
    blank_dropdowns = [
        {"id": f["id"], "value": None}
        for f in fields if f.get("type") == "drop_down" and f["id"] != f_calendar["id"]
    ]

    created: dict[str, str] = {}
    for task in schedule.tasks:
        payload: dict = {"name": task.name, "custom_fields": list(blank_dropdowns)}
        if task.parent_key:
            payload["parent"] = created[task.parent_key]
        if not task.is_summary:
            _, status = reconcile_leaf(task.percent, names.open, "open", None, None, names)
            payload["status"] = status
            payload["custom_fields"] += [
                {"id": f_duration["id"], "value": task.duration},
                {"id": f_percent["id"], "value": {"current": task.percent}},
                {"id": f_calendar["id"], "value": calendar_option_id(f_calendar, task.calendar)},
            ]
        team_ids = []
        for resource in task.resources:
            if _team_key(resource) in groups:
                team_ids.append(groups[_team_key(resource)])
            else:
                print(f'  AVISO: equipe "{resource}" não existe no ClickUp ({task.name})')
        if team_ids:
            payload["group_assignees"] = team_ids
        try:
            result = await call(lambda p=payload: clickup.create_raw_task(lst["id"], p), idempotent=False)
        except httpx.HTTPStatusError as exc:
            if "group_assignees" not in payload or exc.response.status_code not in (400, 401, 403):
                raise
            # um membro da equipe sem acesso à lista faz o ClickUp recusar a tarefa inteira
            print(f'  AVISO: "{task.name}" criada sem equipe — {exc.response.text[:120]}')
            payload.pop("group_assignees")
            result = await call(lambda p=payload: clickup.create_raw_task(lst["id"], p), idempotent=False)
        created[task.key] = result["id"]
    return created


async def create_dependencies(clickup: ClickUpClient, schedule: XlsxSchedule, created: dict[str, str]) -> int:
    count = 0
    for task in schedule.tasks:
        for predecessor in task.predecessors:
            await call(lambda t=task, p=predecessor: clickup.add_dependency(created[t.key], created[p]))
            count += 1
    return count


async def ensure_holidays(clickup: ClickUpClient, list_id: str, schedule: XlsxSchedule) -> int:
    existing = await call(lambda: clickup.get_tasks(list_id, include_closed=True))
    known = {ms_to_date(t.get("due_date")) for t in existing}
    added = 0
    for day, name in schedule.holidays:
        if day not in known:
            await call(lambda d=day, n=name: clickup.create_raw_task(
                list_id, {"name": n or f"Feriado {d:%d/%m/%Y}", "due_date": date_to_ms(d), "due_date_time": False}
            ), idempotent=False)
            added += 1
    return added


async def main(args: argparse.Namespace) -> int:
    schedule = load_schedule(args.files)
    if args.zero:
        # mesma estrutura, sem andamento: modelo para uma província que ainda não começou
        schedule = dataclasses.replace(
            schedule, tasks=tuple(dataclasses.replace(task, percent=0.0) for task in schedule.tasks)
        )
    if args.no_start_date:
        # província sem data definida: o motor não calcula nada até a lista ganhar início
        schedule = dataclasses.replace(schedule, start=None)
    if args.start_date:
        schedule = dataclasses.replace(schedule, start=datetime.strptime(args.start_date, "%d/%m/%Y").date())
    describe(schedule)
    if not args.yes:
        print("\nENSAIO: nada foi escrito no ClickUp. Rode com --yes para executar.")
        return 0

    async with ClickUpClient() as clickup:
        if args.list_id:
            lst = await call(lambda: clickup.get_list(args.list_id))
        else:
            created_list = await call(lambda: clickup.create_list_in_folder(args.folder_id, args.list_name), idempotent=False)
            lst = await call(lambda: clickup.get_list(created_list["id"]))
        list_id = lst["id"]
        print(f'\nLista: {lst["name"]} ({list_id})')

        existing = await call(lambda: clickup.get_tasks(list_id, include_closed=True))
        if existing and not args.replace:
            print(f"ERRO: a lista já tem {len(existing)} tarefas. Use --replace para apagá-las antes de importar.")
            return 1
        if existing and args.replace != lst["name"]:
            print(f'ERRO: --replace tem de repetir o nome exato da lista ("{lst["name"]}") para confirmar '
                  f"que é ela que vai perder as {len(existing)} tarefas.")
            return 1
        if existing:
            print(f"  apagando {len(existing)} tarefas existentes…")
            await delete_existing(clickup, list_id)

        fields = await ensure_fields(clickup, list_id)
        await configure_list(clickup, lst, schedule)
        created = await create_tasks(clickup, lst, fields, schedule)
        print(f"  {len(created)} tarefas criadas")
        print(f"  {await create_dependencies(clickup, schedule, created)} dependências criadas")
        views = await ensure_views(clickup, list_id, fields)
        if views:
            print(f"  vistas criadas: {', '.join(views)}")

        if args.holidays_list_id:
            print(f"  {await ensure_holidays(clickup, args.holidays_list_id, schedule)} feriados adicionados")

        if args.recalculate and not schedule.start:
            print("  sem data de início: o motor não foi executado e as tarefas ficam sem datas")
        elif args.recalculate:
            await init_db()
            async with AsyncSessionLocal() as db:
                summary = await ScheduleService(db, clickup).recalculate(list_id)
            print(f"  motor: {summary.changed} tarefas atualizadas, {summary.writes} gravações, "
                  f"fim previsto {summary.project_finish}, {summary.percent}% concluído")
            for message in summary.warnings + summary.errors:
                print(f"  ! {message}")
            if not summary.ok:
                return 1
    print("\nConcluído.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="planilhas, na ordem das disciplinas (civil, logística, técnica)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--list-id", help="lista existente que vai receber o cronograma")
    target.add_argument("--folder-id", help="pasta onde criar uma lista nova")
    parser.add_argument("--list-name", default="Site FM", help="nome da lista nova (com --folder-id)")
    parser.add_argument("--replace", metavar="NOME_DA_LISTA",
                        help="apaga as tarefas que já existem na lista; exige o nome exato dela como confirmação")
    parser.add_argument("--zero", action="store_true", help="importa a estrutura com todo o progresso em 0%%")
    parser.add_argument("--no-start-date", action="store_true",
                        help="não define a data de início da lista; as tarefas ficam sem datas até ela ser preenchida")
    parser.add_argument("--start-date", metavar="DD/MM/AAAA", help="data de início do projeto (padrão: a da planilha)")
    parser.add_argument("--holidays-list-id", help="lista de feriados a completar com os da planilha")
    parser.add_argument("--recalculate", action="store_true", help="roda o motor ao final para gravar as datas")
    parser.add_argument("--yes", action="store_true", help="executa de verdade")
    sys.exit(asyncio.run(main(parser.parse_args())))
