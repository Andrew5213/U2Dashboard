"""Liga o motor do cronograma (schedule_engine) a uma lista do ClickUp.

Lê a lista inteira, calcula, compara com o que já está gravado e escreve só as
diferenças — é isso que impede o laço webhook → recálculo → webhook: a segunda
passada não encontra nada para gravar.

Datas digitadas à mão: o motor guarda as datas que deixou em cada tarefa
(`schedule_task_state`). Uma data diferente foi mexida por alguém e vira entrada
do cálculo — início → "Início fixado" (não começar antes de), vencimento → nova
duração — e só essa tarefa e as que dependem dela (com os resumos que as contêm)
têm as datas regravadas; o resto da lista fica como está.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.models.schedule_models import ScheduleBaseline, ScheduleTaskState
from src.services.clickup_client import ClickUpClient
from src.services.schedule_engine import (
    CAL_CORRIDO,
    ScheduleTask,
    StatusNames,
    WorkCalendar,
    compute_schedule,
    dependents_of,
    display_percent,
    reconcile_leaf,
    summary_status,
    workdays_between,
)
from src.services.schedule_fields import (
    FIELD_CALENDAR,
    FIELD_COMPLETION,
    FIELD_DEFS,
    FIELD_DURATION,
    FIELD_FIXED_START,
    FIELD_PERCENT,
    date_to_ms,
    find_field,
    ms_to_site_date,
    norm,
    parse_weekend_mask,
    read_calendar,
    read_number,
    read_percent,
)

_WRITE_PAUSE_SECONDS = 0.15
_WRITE_CONCURRENCY = 4
_MAX_ATTEMPTS = 5
_HOLIDAYS_TTL_SECONDS = 600
_holidays_cache: dict[str, tuple[float, frozenset[date]]] = {}


@dataclass
class ScheduleRunSummary:
    list_id: str
    dry_run: bool = False
    tasks: int = 0
    changed: int = 0
    writes: int = 0
    percent: float | None = None
    project_start: date | None = None
    project_finish: date | None = None
    # Linha de base: término planeado e o desvio do término atual, em dias corridos
    # (positivo = atrasado). `baseline_captured` diz se foi gravada nesta execução.
    baseline_finish: date | None = None
    delay_days: int | None = None
    baseline_captured: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class _Current:
    """O que está gravado no ClickUp para uma tarefa."""
    id: str
    name: str
    parent_id: str | None
    status: str
    status_type: str | None
    percent: float
    duration: float | None
    calendar: str
    start: date | None
    due: date | None
    completed_on: date | None
    predecessors: tuple[str, ...]
    fixed_start: date | None = None
    start_raw: int | None = None      # o instante gravado, para normalizar datas digitadas
    due_raw: int | None = None


@dataclass(frozen=True)
class _Edit:
    """O que o utilizador mudou à mão numa tarefa-folha e o efeito no cálculo."""
    start_changed: bool
    due_changed: bool
    fixed_start: date | None = None      # novo "não começar antes de"
    duration: float | None = None        # nova duração
    completed_on: date | None = None     # nova data real (tarefa concluída)
    problem: str | None = None


def status_names(statuses: list[dict] | None) -> StatusNames:
    """Trio aberto / em andamento / concluído a partir dos statuses da lista."""
    statuses = sorted(statuses or [], key=lambda s: s.get("orderindex", 0))
    by_type = lambda kind: next((s["status"] for s in statuses if s.get("type") == kind), None)  # noqa: E731
    open_name = by_type("open") or (statuses[0]["status"] if statuses else "planejando")
    done_name = by_type("done") or "complete"
    in_progress = next((s["status"] for s in statuses if norm(s["status"]) == "fazendo"), None)
    return StatusNames(open=open_name, in_progress=in_progress or by_type("custom") or open_name, done=done_name)


class ScheduleService:
    def __init__(self, db: AsyncSession, clickup: ClickUpClient) -> None:
        self._db = db
        self._clickup = clickup

    async def recalculate(
        self, list_id: str, dry_run: bool = False, today: date | None = None, rebaseline: bool = False,
    ) -> ScheduleRunSummary:
        """`rebaseline=True` adota o cronograma atual como a nova linha de base (com
        `dry_run=True` faz só isso, sem gravar nada no ClickUp)."""
        summary = ScheduleRunSummary(list_id=list_id, dry_run=dry_run)
        today = today or local_today()
        try:
            await self._run(list_id, dry_run, today, summary, rebaseline)
        except Exception as exc:  # noqa: BLE001 — o worker não pode morrer por uma lista
            logger.exception(f"Cronograma: falha ao recalcular a lista {list_id}")
            summary.errors.append(f"{type(exc).__name__}: {exc}")
        return summary

    async def _run(
        self, list_id: str, dry_run: bool, today: date, summary: ScheduleRunSummary, rebaseline: bool = False,
    ) -> None:
        lst = await self._call(lambda: self._clickup.get_list(list_id))
        fields = await self._call(lambda: self._clickup.get_list_fields(list_id))
        f_percent = find_field(fields, FIELD_PERCENT, "manual_progress")
        f_duration = find_field(fields, FIELD_DURATION, "number")
        f_completion = find_field(fields, FIELD_COMPLETION, "date")
        if not f_percent or not f_duration:
            summary.errors.append(f'lista sem os campos "{FIELD_PERCENT}" e "{FIELD_DURATION}" — não é um cronograma')
            return
        if not f_completion:
            # sem onde guardar a data real, uma tarefa concluída "terminaria hoje" todo dia
            summary.errors.append(f'lista sem o campo "{FIELD_COMPLETION}" (tipo data)')
            return

        start = _site(lst.get("start_date"))
        if not start:
            summary.errors.append("lista sem data de início — defina a data de início da lista no ClickUp")
            return

        calendar = WorkCalendar(
            start=start,
            weekend_mask=parse_weekend_mask(lst.get("content"), settings.schedule_weekend_mask),
            holidays=await self._holidays(),
        )
        names = status_names(lst.get("statuses"))

        raw_tasks = await self._call(lambda: self._clickup.get_tasks(list_id, include_closed=True))
        current = _parse_tasks(raw_tasks)
        summary.tasks = len(current)
        if not current:
            return

        parents = {c.parent_id for c in current.values() if c.parent_id}
        depth = _depths(current)
        for c in current.values():
            if c.id not in parents and c.duration is None and c.status_type != "closed":
                summary.warnings.append(f'"{c.name}": sem duração — não pesa no progresso nem ocupa o cronograma')
        previous = await self._load_state(list_id)

        engine_tasks: list[ScheduleTask] = []
        leaf_target: dict[str, tuple[float, str, date | None]] = {}
        edits: dict[str, _Edit] = {}
        for c in current.values():
            if c.id in parents:
                engine_tasks.append(ScheduleTask(id=c.id, parent_id=c.parent_id, predecessors=c.predecessors))
                continue
            prev = previous.get(c.id)
            percent, status = reconcile_leaf(
                c.percent, c.status, c.status_type,
                prev.percent if prev else None, prev.is_done if prev else None, names,
            )
            cancelled = c.status_type == "closed"
            edit = None if cancelled else _detect_edit(c, prev, percent, calendar)
            if edit:
                edits[c.id] = edit
                if edit.problem:
                    summary.warnings.append(f'"{c.name}": {edit.problem}')
            completed_on = None
            if percent >= 100 and not cancelled:
                # sem data real informada, a conclusão vale a partir de hoje
                completed_on = (edit.completed_on if edit else None) or c.completed_on or today
            leaf_target[c.id] = (percent, status, completed_on)
            duration = edit.duration if edit and edit.duration is not None else c.duration
            engine_tasks.append(ScheduleTask(
                id=c.id, parent_id=c.parent_id, duration=duration or 0.0, calendar=c.calendar,
                percent=percent, predecessors=c.predecessors, start=c.start,
                finished_on=completed_on, cancelled=cancelled,
                not_before=(edit.fixed_start if edit else None) or c.fixed_start,
            ))

        # Edição à mão: só a tarefa mexida e as que dependem dela são recalculadas;
        # as demais ficam com as datas de agora.
        date_scope: set[str] | None = None
        if edits:
            affected = dependents_of(engine_tasks, set(edits))
            engine_tasks = [_pin_outside(t, affected, parents, current) for t in engine_tasks]
            date_scope = affected | _ancestors(affected, current)
            logger.info(
                f"Cronograma [{list_id}]: {len(edits)} data(s) mudada(s) à mão — "
                f"{len(affected)} tarefa(s) a recalcular"
            )

        f_fixed = find_field(fields, FIELD_FIXED_START, "date")
        if not f_fixed and not dry_run and any(e.fixed_start for e in edits.values()):
            f_fixed = await self._create_fixed_start_field(list_id, summary)

        output = compute_schedule(engine_tasks, calendar, today, reschedule=True)
        summary.warnings.extend(_named(w, current) for w in output.warnings)
        notices = _start_conflicts(edits, current, output.results, calendar, today)
        summary.warnings.extend(f'"{current[task_id].name}": {text}' for task_id, text in notices)

        leaves = [r for r in output.results.values() if not r.is_summary and r.start]
        if leaves:
            total = sum(r.duration_util for r in leaves)
            summary.percent = round(sum(r.duration_util * r.percent for r in leaves) / total, 2) if total else None
            summary.project_start = min(r.start for r in leaves)
            summary.project_finish = max(r.finish for r in leaves)

        if rebaseline:
            await self._save_baseline(list_id, output.results)
            summary.baseline_captured = True
        elif not dry_run and await self._baseline_finish(list_id) is None:
            # Primeiro cálculo da lista: guarda o plano puro, sem o andamento — é
            # contra ele que o atraso passa a ser medido.
            baseline_plan = compute_schedule(
                [replace(t, percent=0.0, start=None, finished_on=None, not_before=None, pinned=None)
                 for t in engine_tasks],
                calendar, today, reschedule=False,
            )
            await self._save_baseline(list_id, baseline_plan.results)
            summary.baseline_captured = True
        summary.baseline_finish = await self._baseline_finish(list_id)
        if summary.baseline_finish and summary.project_finish:
            summary.delay_days = (summary.project_finish - summary.baseline_finish).days

        plans: list[dict] = []
        for c in sorted(current.values(), key=lambda item: -depth[item.id]):  # folhas antes dos resumos
            result = output.results[c.id]
            dates_allowed = date_scope is None or c.id in date_scope
            if result.is_summary:
                plan = _plan_summary(c, result, names, f_percent, f_duration, dates_allowed)
            elif c.status_type == "closed":
                continue
            else:
                percent, status, completed_on = leaf_target[c.id]
                plan = _plan_leaf(c, result, percent, status, completed_on, names, f_percent, f_completion)
                _plan_edit(c, edits.get(c.id), result, plan, f_duration, f_fixed)
                if not dates_allowed:
                    _drop_dates(plan)
            if plan["task"] or plan["fields"] or plan["clear"]:
                plans.append(plan)
                summary.changes.append({"task_id": c.id, "name": c.name, "changes": plan["log"]})
        summary.changed = len(plans)

        if dry_run:
            return

        failed: set[str] = set()
        written: dict[str, dict] = {}     # tarefa → o que o PUT gravou (datas incluídas)
        semaphore = asyncio.Semaphore(_WRITE_CONCURRENCY)

        async def apply(plan: dict) -> int:
            async with semaphore:
                try:
                    return await self._apply(plan, written)
                except Exception as exc:  # noqa: BLE001 — uma tarefa com erro não trava as outras
                    failed.add(plan["id"])
                    summary.errors.append(f'{plan["name"]}: {_describe(exc)}')
                    return 0

        # Um nível de cada vez, do mais fundo para o topo: um resumo só pode ser
        # concluído depois de as tarefas dele já estarem concluídas no ClickUp.
        by_depth: dict[int, list[dict]] = {}
        for plan in plans:
            by_depth.setdefault(depth[plan["id"]], []).append(plan)
        for level in sorted(by_depth, reverse=True):
            summary.writes += sum(await asyncio.gather(*(apply(plan) for plan in by_depth[level])))

        for task_id, text in notices:
            try:
                await self._call(lambda t=task_id, x=text: self._clickup.create_comment(t, x, notify_all=False))
                summary.writes += 1
            except Exception as exc:  # noqa: BLE001 — o aviso não pode desfazer o cálculo
                summary.errors.append(f"{current[task_id].name}: comentário não publicado — {_describe(exc)}")

        await self._save_state(list_id, current, leaf_target, names, failed, written, previous)
        logger.info(
            f"Cronograma [{list_id}]: {summary.tasks} tarefas, {summary.changed} alteradas, "
            f"{summary.writes} gravações, {len(summary.errors)} erro(s)"
        )

    # ─── Gravação ────────────────────────────────────────────────────────────

    async def _apply(self, plan: dict, written: dict[str, dict]) -> int:
        writes = 0
        task_id = plan["id"]
        if plan["task"]:
            await self._call(lambda: self._clickup.update_task_fields(task_id, plan["task"]))
            written[task_id] = plan["task"]
            writes += 1
        for field_id, value in plan["fields"]:
            await self._call(lambda f=field_id, v=value: self._clickup.set_custom_field(task_id, f, v))
            writes += 1
        for field_id in plan["clear"]:
            await self._call(lambda f=field_id: self._clickup.clear_custom_field(task_id, f))
            writes += 1
        return writes

    async def _call(self, factory):
        """Executa uma chamada ao ClickUp com espera em 429 e nova tentativa em falha de rede."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                result = await factory()
                await asyncio.sleep(_WRITE_PAUSE_SECONDS)
                return result
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429 or attempt == _MAX_ATTEMPTS:
                    raise
                wait = rate_limit_wait(exc.response)
                logger.warning(f"Cronograma: limite de requisições do ClickUp, aguardando {wait:.0f}s")
                await asyncio.sleep(wait)
            except httpx.TransportError:
                if attempt == _MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(2 * attempt)
        raise RuntimeError("unreachable")

    async def _create_fixed_start_field(self, list_id: str, summary: ScheduleRunSummary) -> dict | None:
        """As listas importadas antes deste recurso não têm o campo "Início fixado"."""
        definition = next(d for d in FIELD_DEFS if d["name"] == FIELD_FIXED_START)
        try:
            await self._call(lambda: self._clickup.create_custom_field(list_id, definition))
            fields = await self._call(lambda: self._clickup.get_list_fields(list_id))
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f'campo "{FIELD_FIXED_START}" não foi criado — {_describe(exc)}')
            return None
        logger.info(f'Cronograma [{list_id}]: campo "{FIELD_FIXED_START}" criado')
        return find_field(fields, FIELD_FIXED_START, "date")

    # ─── Feriados ────────────────────────────────────────────────────────────

    async def _holidays(self) -> frozenset[date]:
        """Cada tarefa da lista de feriados é um dia não trabalhado (data = vencimento)."""
        list_id = settings.schedule_holidays_list_id
        if not list_id:
            return frozenset()
        cached = _holidays_cache.get(list_id)
        if cached and time.monotonic() - cached[0] < _HOLIDAYS_TTL_SECONDS:
            return cached[1]
        tasks = await self._call(lambda: self._clickup.get_tasks(list_id, include_closed=True))
        days = frozenset(
            day for day in (_site(t.get("due_date") or t.get("start_date")) for t in tasks) if day
        )
        _holidays_cache[list_id] = (time.monotonic(), days)
        return days

    # ─── Linha de base ───────────────────────────────────────────────────────

    async def _baseline_finish(self, list_id: str) -> date | None:
        return (await self._db.execute(
            select(func.max(ScheduleBaseline.finish)).where(ScheduleBaseline.list_id == list_id)
        )).scalar()

    async def _save_baseline(self, list_id: str, results: dict) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._db.execute(delete(ScheduleBaseline).where(ScheduleBaseline.list_id == list_id))
        rows = [
            {"task_id": r.id, "list_id": list_id, "start": r.start, "finish": r.finish, "captured_at": now}
            for r in results.values() if r.start and r.finish
        ]
        if rows:
            # uma tarefa movida de outra lista pode já ter linha própria
            await self._db.execute(delete(ScheduleBaseline).where(
                ScheduleBaseline.task_id.in_([row["task_id"] for row in rows])
            ))
            await self._db.execute(sqlite_insert(ScheduleBaseline), rows)
        await self._db.commit()
        logger.info(f"Cronograma [{list_id}]: linha de base gravada ({len(rows)} tarefas)")

    # ─── Estado anterior ─────────────────────────────────────────────────────

    async def _load_state(self, list_id: str) -> dict[str, ScheduleTaskState]:
        rows = (await self._db.execute(
            select(ScheduleTaskState).where(ScheduleTaskState.list_id == list_id)
        )).scalars().all()
        return {row.task_id: row for row in rows}

    async def _save_state(
        self,
        list_id: str,
        current: dict[str, _Current],
        leaf_target: dict[str, tuple[float, str, date | None]],
        names: StatusNames,
        failed: set[str],
        written: dict[str, dict],
        previous: dict[str, ScheduleTaskState],
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for task_id, (percent, status, _) in leaf_target.items():
            c = current[task_id]
            start, due = _dates_now(c, written.get(task_id))
            if task_id in failed:
                # % e status ficam como estavam; as datas, se o PUT passou, já mudaram
                prev = previous.get(task_id)
                if not prev:
                    continue
                percent, is_done = prev.percent, prev.is_done
            else:
                is_done = norm(status) == norm(names.done) or (
                    c.status_type == "done" and norm(status) == norm(c.status))
            values = {"list_id": list_id, "percent": percent, "is_done": is_done,
                      "start": start, "due": due, "updated_at": now}
            stmt = sqlite_insert(ScheduleTaskState).values(task_id=task_id, **values)
            await self._db.execute(stmt.on_conflict_do_update(index_elements=["task_id"], set_=values))
        await self._db.execute(delete(ScheduleTaskState).where(
            ScheduleTaskState.list_id == list_id,
            ScheduleTaskState.task_id.notin_(list(current)),
        ))
        await self._db.commit()


def local_today() -> date:
    """Hoje no fuso da obra — em UTC, a virada do dia cairia no meio do expediente
    de quem está noutro fuso."""
    return (datetime.now(timezone.utc) + timedelta(hours=settings.schedule_utc_offset_hours)).date()


def rate_limit_wait(response: httpx.Response) -> float:
    """Segundos a esperar após um 429. O ClickUp informa a hora da renovação em
    X-RateLimit-Reset (epoch em segundos); Retry-After fica como alternativa."""
    reset = response.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            return min(max(float(reset) - time.time(), 1.0), 60.0)
        except ValueError:
            pass
    try:
        return min(max(float(response.headers.get("Retry-After", "10")), 1.0), 60.0)
    except ValueError:
        return 10.0


def invalidate_holidays_cache() -> None:
    _holidays_cache.clear()


def _site(ms) -> date | None:
    return ms_to_site_date(ms, settings.schedule_utc_offset_hours)


def _raw(ms) -> int | None:
    try:
        return int(ms) if ms not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ─── Funções puras: leitura e plano de gravação ──────────────────────────────

def _parse_tasks(raw_tasks: list[dict]) -> dict[str, _Current]:
    ids = {str(t["id"]) for t in raw_tasks}
    predecessors: dict[str, set[str]] = {}
    for t in raw_tasks:
        for dep in t.get("dependencies") or []:
            # type 1 = "task_id espera por depends_on"; o registo aparece nas duas tarefas
            if dep.get("type", 1) == 1 and dep.get("task_id") and dep.get("depends_on"):
                predecessors.setdefault(str(dep["task_id"]), set()).add(str(dep["depends_on"]))

    current: dict[str, _Current] = {}
    for t in raw_tasks:
        task_id = str(t["id"])
        custom = t.get("custom_fields") or []
        status = t.get("status") or {}
        parent = str(t["parent"]) if t.get("parent") else None
        current[task_id] = _Current(
            id=task_id,
            name=t.get("name", ""),
            parent_id=parent if parent in ids else None,
            status=status.get("status") or "",
            status_type=status.get("type"),
            percent=read_percent(find_field(custom, FIELD_PERCENT, "manual_progress")) or 0.0,
            duration=read_number(find_field(custom, FIELD_DURATION, "number")),
            calendar=read_calendar(find_field(custom, FIELD_CALENDAR, "drop_down")),
            start=_site(t.get("start_date")),
            due=_site(t.get("due_date")),
            completed_on=_site((find_field(custom, FIELD_COMPLETION, "date") or {}).get("value")),
            predecessors=tuple(sorted(predecessors.get(task_id, ()))),
            fixed_start=_site((find_field(custom, FIELD_FIXED_START, "date") or {}).get("value")),
            start_raw=_raw(t.get("start_date")),
            due_raw=_raw(t.get("due_date")),
        )
    return current


def _depths(current: dict[str, _Current]) -> dict[str, int]:
    depth: dict[str, int] = {}

    def walk(task_id: str) -> int:
        if task_id not in depth:
            parent = current[task_id].parent_id
            depth[task_id] = 0 if not parent else walk(parent) + 1
        return depth[task_id]

    for task_id in current:
        walk(task_id)
    return depth


def _ancestors(task_ids: set[str], current: dict[str, _Current]) -> set[str]:
    found: set[str] = set()
    for task_id in task_ids:
        parent = current[task_id].parent_id
        while parent and parent not in found:
            found.add(parent)
            parent = current[parent].parent_id
    return found


def _pin_outside(task: ScheduleTask, affected: set[str], parents: set, current: dict[str, _Current]) -> ScheduleTask:
    """Tarefa-folha fora do alcance da edição fica com as datas que já tem."""
    c = current[task.id]
    if task.id in parents or task.id in affected or task.cancelled or not (c.start and c.due):
        return task
    return replace(task, pinned=(c.start, c.due))


def _detect_edit(c: _Current, prev: ScheduleTaskState | None, percent: float, calendar: WorkCalendar) -> _Edit | None:
    """Data de uma tarefa-folha diferente da que o motor deixou nela = mexida à mão.

    Sem estado anterior com datas (tarefa nova, ou estado de antes deste recurso)
    nada conta como edição. Data apagada também não: o motor volta a preenchê-la.
      - não iniciada: o início vira "não começar antes de"; o vencimento vira a
        duração (dias úteis do início ao vencimento) — mover as duas datas juntas,
        com a mesma distância entre elas, é só mudar de lugar e mantém a duração;
      - em andamento: o início já vale como início real; o vencimento vira duração;
      - concluída: o vencimento vira a data real de conclusão.
    """
    if not prev or (prev.start is None and prev.due is None):
        return None
    start_changed = c.start is not None and c.start != prev.start
    due_changed = c.due is not None and c.due != prev.due
    if not (start_changed or due_changed):
        return None
    if percent >= 100:
        return _Edit(start_changed, due_changed, completed_on=c.due if due_changed else None)

    fixed_start = c.start if start_changed and percent <= 0 else None
    moved = False
    if start_changed and due_changed and c.start and c.due and prev.start and prev.due:
        moved = (c.due - c.start) == (prev.due - prev.start)
    duration, problem = None, None
    if due_changed and not moved:
        duration, problem = _duration_between(c, calendar)
    return _Edit(start_changed, due_changed, fixed_start=fixed_start, duration=duration, problem=problem)


def _duration_between(c: _Current, calendar: WorkCalendar) -> tuple[float | None, str | None]:
    start, due = c.start, c.due
    if not start or not due or due < start:
        return None, "vencimento antes do início — a duração não foi alterada"
    if c.calendar == CAL_CORRIDO:
        return float((due - start).days + 1), None
    days = workdays_between(calendar, start, due)
    if days <= 0:
        return None, "início e vencimento em dias de folga — a duração não foi alterada"
    return float(days), None


def _start_conflicts(
    edits: dict[str, _Edit], current: dict[str, _Current], results: dict, calendar: WorkCalendar, today: date,
) -> list[tuple[str, str]]:
    """Início digitado que o cálculo não pôde respeitar — vira comentário na tarefa.
    Um início num dia de folga que só passou para o dia útil seguinte não é conflito."""
    notices: list[tuple[str, str]] = []
    for task_id, edit in edits.items():
        wanted, result = edit.fixed_start, results.get(task_id)
        if not wanted or not result or not result.start:
            continue
        first_workday = calendar.date_at(calendar.index_of(wanted))   # o próprio dia, ou o próximo útil
        if result.start <= first_workday:
            continue
        finishes = [
            (results[p].finish, current[p].name) for p in current[task_id].predecessors
            if p in results and results[p].finish
        ]
        last = max(finishes, default=None)
        # o que de fato segurou o início: hoje (data no passado) ou a antecessora
        if calendar.index_of(wanted) < calendar.index_of(today) and calendar.date_at(calendar.index_of(today)) >= result.start:
            reason = f"{wanted:%d/%m/%Y} já passou e a tarefa não foi iniciada"
        elif last and calendar.date_at(calendar.end_position(last[0])) >= result.start:
            reason = f'ela depende de "{last[1]}", que termina em {last[0]:%d/%m/%Y}'
        else:
            reason = f"o primeiro dia útil possível é {result.start:%d/%m/%Y}"
        notices.append((task_id, (
            f"Cronograma: o início em {wanted:%d/%m/%Y} não foi possível — {reason}. "
            f"Início ajustado para {result.start:%d/%m/%Y}."
        )))
    return notices


def _dates_now(c: _Current, put: dict | None) -> tuple[date | None, date | None]:
    """Datas que ficaram no ClickUp depois das gravações desta execução."""
    start, due = c.start, c.due
    if put and "start_date" in put:
        start = _site(put["start_date"])
    if put and "due_date" in put:
        due = _site(put["due_date"])
    return start, due


def _date_changes(
    c: _Current, start: date | None, finish: date | None, plan: dict, normalize: bool = False,
) -> None:
    """`normalize`: data digitada à mão é regravada pelo motor mesmo que o dia não
    mude. Quem digitou em Angola deixa a meia-noite UTC+1 — o dia anterior em UTC,
    que é como a dashboard e os relatórios leem. Regravada, a data passa a ser a
    meia-noite do fuso do token da app (o ClickUp guarda data sem hora assim:
    03:00 UTC), que cai no mesmo dia nas duas leituras."""
    if start and (start != c.start or (normalize and c.start_raw != date_to_ms(start))):
        plan["task"].update({"start_date": date_to_ms(start), "start_date_time": False})
        if start != c.start:
            plan["log"]["inicio"] = [_iso(c.start), _iso(start)]
    if finish and (finish != c.due or (normalize and c.due_raw != date_to_ms(finish))):
        plan["task"].update({"due_date": date_to_ms(finish), "due_date_time": False})
        if finish != c.due:
            plan["log"]["fim"] = [_iso(c.due), _iso(finish)]


def _drop_dates(plan: dict) -> None:
    for key in ("start_date", "start_date_time", "due_date", "due_date_time"):
        plan["task"].pop(key, None)
    for key in ("inicio", "fim"):
        plan["log"].pop(key, None)


def _plan_edit(c: _Current, edit: _Edit | None, result, plan: dict, f_duration, f_fixed) -> None:
    """Grava o que uma data digitada virou: duração nova e/ou "Início fixado"."""
    if not edit:
        return
    _date_changes(c, result.start, result.finish, plan, normalize=True)
    if edit.duration is not None and (c.duration is None or abs(edit.duration - c.duration) > 0.005):
        plan["fields"].append((f_duration["id"], _number(edit.duration)))
        plan["log"]["duracao"] = [c.duration, edit.duration]
    if edit.fixed_start and edit.fixed_start != c.fixed_start:
        if f_fixed:
            plan["fields"].append((f_fixed["id"], date_to_ms(edit.fixed_start)))
        plan["log"]["inicio_fixado"] = [_iso(c.fixed_start), _iso(edit.fixed_start)]


def _plan_leaf(c, result, percent, status, completed_on, names, f_percent, f_completion) -> dict:
    plan = {"id": c.id, "name": c.name, "task": {}, "fields": [], "clear": [], "log": {}}
    _date_changes(c, result.start, result.finish, plan)
    if norm(status) != norm(c.status):
        plan["task"]["status"] = status
        plan["log"]["status"] = [c.status, status]
    if abs(percent - c.percent) > 0.01:
        plan["fields"].append((f_percent["id"], {"current": _number(percent)}))
        plan["log"]["percentual"] = [c.percent, percent]
    if f_completion and completed_on != c.completed_on:
        if completed_on:
            plan["fields"].append((f_completion["id"], date_to_ms(completed_on)))
        else:
            plan["clear"].append(f_completion["id"])
        plan["log"]["conclusao"] = [_iso(c.completed_on), _iso(completed_on)]
    return plan


def _plan_summary(c, result, names: StatusNames, f_percent, f_duration, dates_allowed: bool = True) -> dict:
    plan = {"id": c.id, "name": c.name, "task": {}, "fields": [], "clear": [], "log": {}}
    if dates_allowed:
        _date_changes(c, result.start, result.finish, plan)
    status = summary_status(result.percent, c.status, c.status_type, names)
    if norm(status) != norm(c.status):
        plan["task"]["status"] = status
        plan["log"]["status"] = [c.status, status]
    percent = display_percent(result.percent)
    if abs(percent - c.percent) > 0.01:
        plan["fields"].append((f_percent["id"], {"current": percent}))
        plan["log"]["percentual"] = [c.percent, percent]
    duration = round(result.duration, 2)
    if dates_allowed and (c.duration is None or abs(duration - c.duration) > 0.005):
        plan["fields"].append((f_duration["id"], duration))
        plan["log"]["duracao"] = [c.duration, duration]
    return plan


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 2)


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _named(warning: str, current: dict[str, _Current]) -> str:
    """Troca os ids marcados pelo motor ([[id]]) pelo nome da tarefa."""
    def name(match: re.Match) -> str:
        task = current.get(match.group(1))
        return f'"{task.name}"' if task else match.group(1)

    return re.sub(r"\[\[(.+?)\]\]", name, warning)


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} {exc.response.text[:200]}"
    return f"{type(exc).__name__}: {exc}"
