"""Liga o motor do cronograma (schedule_engine) a uma lista do ClickUp.

Lê a lista inteira, calcula, compara com o que já está gravado e escreve só as
diferenças — é isso que impede o laço webhook → recálculo → webhook: a segunda
passada não encontra nada para gravar.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.models.schedule_models import ScheduleTaskState
from src.services.clickup_client import ClickUpClient
from src.services.schedule_engine import (
    ScheduleTask,
    StatusNames,
    WorkCalendar,
    compute_schedule,
    display_percent,
    reconcile_leaf,
    summary_status,
)
from src.services.schedule_fields import (
    FIELD_CALENDAR,
    FIELD_COMPLETION,
    FIELD_DURATION,
    FIELD_PERCENT,
    date_to_ms,
    find_field,
    ms_to_date,
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
        self, list_id: str, dry_run: bool = False, today: date | None = None
    ) -> ScheduleRunSummary:
        summary = ScheduleRunSummary(list_id=list_id, dry_run=dry_run)
        today = today or local_today()
        try:
            await self._run(list_id, dry_run, today, summary)
        except Exception as exc:  # noqa: BLE001 — o worker não pode morrer por uma lista
            logger.exception(f"Cronograma: falha ao recalcular a lista {list_id}")
            summary.errors.append(f"{type(exc).__name__}: {exc}")
        return summary

    async def _run(self, list_id: str, dry_run: bool, today: date, summary: ScheduleRunSummary) -> None:
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

        start = ms_to_date(lst.get("start_date"))
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
            completed_on = None
            if percent >= 100 and not cancelled:
                # sem data real informada, a conclusão vale a partir de hoje
                completed_on = c.completed_on or today
            leaf_target[c.id] = (percent, status, completed_on)
            engine_tasks.append(ScheduleTask(
                id=c.id, parent_id=c.parent_id, duration=c.duration or 0.0, calendar=c.calendar,
                percent=percent, predecessors=c.predecessors, start=c.start,
                finished_on=completed_on, cancelled=cancelled,
            ))

        output = compute_schedule(engine_tasks, calendar, today, reschedule=True)
        summary.warnings.extend(_named(w, current) for w in output.warnings)

        leaves = [r for r in output.results.values() if not r.is_summary and r.start]
        if leaves:
            total = sum(r.duration_util for r in leaves)
            summary.percent = round(sum(r.duration_util * r.percent for r in leaves) / total, 2) if total else None
            summary.project_start = min(r.start for r in leaves)
            summary.project_finish = max(r.finish for r in leaves)

        plans: list[dict] = []
        for c in sorted(current.values(), key=lambda item: -depth[item.id]):  # folhas antes dos resumos
            result = output.results[c.id]
            if result.is_summary:
                plan = _plan_summary(c, result, names, f_percent, f_duration)
            elif c.status_type == "closed":
                continue
            else:
                percent, status, completed_on = leaf_target[c.id]
                plan = _plan_leaf(c, result, percent, status, completed_on, names, f_percent, f_completion)
            if plan["task"] or plan["fields"] or plan["clear"]:
                plans.append(plan)
                summary.changes.append({"task_id": c.id, "name": c.name, "changes": plan["log"]})
        summary.changed = len(plans)

        if dry_run:
            return

        failed: set[str] = set()
        semaphore = asyncio.Semaphore(_WRITE_CONCURRENCY)

        async def apply(plan: dict) -> int:
            async with semaphore:
                try:
                    return await self._apply(plan)
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

        await self._save_state(list_id, current, leaf_target, names, failed)
        logger.info(
            f"Cronograma [{list_id}]: {summary.tasks} tarefas, {summary.changed} alteradas, "
            f"{summary.writes} gravações, {len(summary.errors)} erro(s)"
        )

    # ─── Gravação ────────────────────────────────────────────────────────────

    async def _apply(self, plan: dict) -> int:
        writes = 0
        task_id = plan["id"]
        if plan["task"]:
            await self._call(lambda: self._clickup.update_task_fields(task_id, plan["task"]))
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
            day for day in (ms_to_date(t.get("due_date") or t.get("start_date")) for t in tasks) if day
        )
        _holidays_cache[list_id] = (time.monotonic(), days)
        return days

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
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for task_id, (percent, status, _) in leaf_target.items():
            if task_id in failed:
                continue
            c = current[task_id]
            is_done = norm(status) == norm(names.done) or (c.status_type == "done" and norm(status) == norm(c.status))
            stmt = sqlite_insert(ScheduleTaskState).values(
                task_id=task_id, list_id=list_id, percent=percent, is_done=is_done,
                updated_at=now,
            )
            await self._db.execute(stmt.on_conflict_do_update(
                index_elements=["task_id"],
                set_={"list_id": list_id, "percent": percent, "is_done": is_done, "updated_at": now},
            ))
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
            start=ms_to_date(t.get("start_date")),
            due=ms_to_date(t.get("due_date")),
            completed_on=ms_to_date((find_field(custom, FIELD_COMPLETION, "date") or {}).get("value")),
            predecessors=tuple(sorted(predecessors.get(task_id, ()))),
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


def _date_changes(c: _Current, start: date | None, finish: date | None, plan: dict) -> None:
    if start and start != c.start:
        plan["task"].update({"start_date": date_to_ms(start), "start_date_time": False})
        plan["log"]["inicio"] = [_iso(c.start), _iso(start)]
    if finish and finish != c.due:
        plan["task"].update({"due_date": date_to_ms(finish), "due_date_time": False})
        plan["log"]["fim"] = [_iso(c.due), _iso(finish)]


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


def _plan_summary(c, result, names: StatusNames, f_percent, f_duration) -> dict:
    plan = {"id": c.id, "name": c.name, "task": {}, "fields": [], "clear": [], "log": {}}
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
    if c.duration is None or abs(duration - c.duration) > 0.005:
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
