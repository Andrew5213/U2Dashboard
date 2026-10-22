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
import math
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
)
from src.services.schedule_pauses import (
    FIELD_PAUSE_FROM,
    FIELD_PAUSE_HISTORY,
    FIELD_PAUSE_REASON,
    FIELD_PAUSE_UNTIL,
    Pause,
    archive,
    blocked_ranges,
    format_history,
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
    read_task_pauses,
)

_WRITE_PAUSE_SECONDS = 0.15
_WRITE_CONCURRENCY = 4
_MAX_ATTEMPTS = 5
_RETRY_DELAY_SECONDS = 2          # × tentativa, em falha de rede ou erro 5xx do ClickUp
_MAX_EDITS_PER_RUN = 10           # acima disto, as "datas digitadas" vêm de um estado velho
_CHECK_EVERY = 8                  # gravações entre duas checagens de "alguém mexeu desde a leitura?"
_CLOCK_MARGIN_MS = 5_000          # folga entre o relógio do servidor e o do ClickUp
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
    pause: Pause | None = None                 # a pausa atual ou a próxima
    history: tuple[Pause, ...] = ()            # pausas já terminadas
    history_bad: tuple[str, ...] = ()          # linhas do histórico que não deu para ler


@dataclass(frozen=True)
class _Prev:
    """O que o motor deixou numa tarefa na execução anterior (tabela schedule_task_state)."""
    percent: float
    is_done: bool
    start: date | None
    due: date | None
    pause: str | None = None


@dataclass(frozen=True)
class _Edit:
    """O que o utilizador mudou à mão numa tarefa-folha e o efeito no cálculo."""
    start_changed: bool
    due_changed: bool
    fixed_start: date | None = None      # novo "começa em" (vence as antecessoras)
    duration: float | None = None        # nova duração
    completed_on: date | None = None     # nova data real (tarefa concluída)
    problem: str | None = None

    def describe(self) -> str:
        """Para o log: o que a data digitada virou."""
        parts = []
        if self.fixed_start:
            parts.append(f"começa em {_iso(self.fixed_start)}")
        if self.duration is not None:
            parts.append(f"duração {self.duration:g}")
        if self.completed_on:
            parts.append(f"concluída em {_iso(self.completed_on)}")
        if self.problem:
            parts.append(self.problem)
        return ", ".join(parts) or "sem efeito"


# Comentários do motor numa tarefa (também vão para os avisos da execução)
_SUMMARY_DUE_NOTICE = (
    "Cronograma: o vencimento de um grupo é calculado pelas tarefas dele — a data {due:%d/%m/%Y} "
    "foi desfeita. Para mudar o fim, altere a duração ou as datas das tarefas; para mover o grupo "
    "inteiro, mude o início dele."
)
_TOP_ROW_NOTICE = (
    "Cronograma: início do projeto alterado para {start:%d/%m/%Y}. Esta linha continua a mostrar "
    "{shown:%d/%m/%Y} porque inclui tarefas iniciadas ou concluídas antes dessa data."
)


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

        read_at_ms = int(time.time() * 1000) - _CLOCK_MARGIN_MS
        raw_tasks = await self._call(lambda: self._clickup.get_tasks(list_id, include_closed=True))
        current = _parse_tasks(raw_tasks)
        summary.tasks = len(current)
        previous = await self._load_state(list_id)
        differing = [c.id for c in current.values()
                     if c.status_type != "closed" and _typed_dates(c, previous.get(c.id))]
        if len(differing) > _MAX_EDITS_PER_RUN:
            # Ninguém mexe em tantas tarefas entre duas execuções: o estado guardado é que está
            # velho (banco restaurado, estado que não chegou a ser salvo). Tomar as diferenças por
            # datas digitadas criaria dezenas de "começa em" falsos — as datas guardadas são
            # descartadas e esta execução só recalcula e regista.
            text = (f"{len(differing)} tarefas com datas diferentes do estado guardado — parece um estado "
                    "antigo; nenhuma foi tratada como data digitada à mão")
            summary.warnings.append(text)
            logger.warning(f"Cronograma [{list_id}]: {text}")
            previous = {k: replace(v, start=None, due=None) for k, v in previous.items()}

        # Início do projeto: a data de início da lista, ou a que alguém pôs na primeira
        # linha (a disciplina do topo) — mudá-la move o projeto inteiro.
        top_id = _top_task_id(raw_tasks, current)
        list_start = _site(lst.get("start_date"))
        start, from_top = _project_start(list_start, current.get(top_id) if top_id else None,
                                         previous.get(top_id) if top_id else None)
        if not start:
            summary.errors.append(
                "lista sem data de início — preencha a data de início da primeira linha (ou da lista) no ClickUp")
            return
        if from_top and start != list_start:
            summary.changes.append({"task_id": list_id, "name": "(início do projeto)",
                                    "changes": {"inicio_projeto": [_iso(list_start), _iso(start)]}})
            if not dry_run:
                await self._call(lambda: self._clickup.update_list(
                    list_id, {"start_date": date_to_ms(start), "start_date_time": False}))
                summary.writes += 1
                logger.info(f"Cronograma [{list_id}]: início do projeto {_iso(list_start)} → {_iso(start)} (primeira linha)")
        if start < today:
            summary.warnings.append(
                f"início do projeto em {start:%d/%m/%Y}, que já passou — as tarefas não iniciadas começam hoje")

        calendar = WorkCalendar(
            start=start,
            weekend_mask=parse_weekend_mask(lst.get("content"), settings.schedule_weekend_mask),
            holidays=await self._holidays(),
        )
        names = status_names(lst.get("statuses"))
        if not current:
            return

        parents = {c.parent_id for c in current.values() if c.parent_id}
        depth = _depths(current)
        for c in current.values():
            if c.id not in parents and c.duration is None and c.status_type != "closed":
                summary.warnings.append(f'"{c.name}": sem duração — não pesa no progresso nem ocupa o cronograma')

        pause_fields = {name: find_field(fields, name, kind) for name, kind in (
            (FIELD_PAUSE_FROM, "date"), (FIELD_PAUSE_UNTIL, "date"),
            (FIELD_PAUSE_REASON, "short_text"), (FIELD_PAUSE_HISTORY, "text"))}
        active, pause_plans = _sort_pauses(current, pause_fields, calendar, today, summary)

        # Datas digitadas num grupo/disciplina. O início vira "não começar antes de" para
        # todas as tarefas do bloco (gravado no "Início fixado" do próprio resumo); um
        # vencimento é desfeito com comentário — o fim de um resumo vem das tarefas dele.
        # A primeira linha fica de fora: o início dela é o início do projeto.
        floors = {c.id: c.fixed_start for c in current.values() if c.id in parents and c.fixed_start}
        block_edits: dict[str, date] = {}
        summary_due_typed: set[str] = set()
        for c in current.values():
            if c.id not in parents or c.status_type == "closed":
                continue
            flags = _typed_dates(c, previous.get(c.id))
            if not flags:
                continue
            start_changed, due_changed, moved = flags
            if start_changed and c.id != top_id and c.start:
                block_edits[c.id] = floors[c.id] = c.start
            if due_changed and not moved:
                summary_due_typed.add(c.id)
        block_floor = _block_floors(current, floors)
        # Mover o bloco leva junto o "começa em" das tarefas dele, pela mesma distância —
        # senão uma tarefa fixada seguraria o bloco no lugar velho (ou perderia a vantagem
        # que tinha sobre a antecessora, se fosse apagado)
        carried: dict[str, date] = {}
        for sid, typed_start in block_edits.items():
            prev_start = previous[sid].start
            if not prev_start:
                continue
            shift = typed_start - prev_start
            for leaf in _leaves_under(sid, current, parents):
                fixed = carried.get(leaf, current[leaf].fixed_start)
                if fixed:
                    carried[leaf] = fixed + shift

        engine_tasks: list[ScheduleTask] = []
        leaf_target: dict[str, tuple[float, str, date | None]] = {}
        touched: dict[str, tuple[bool, bool, bool]] = {}     # folha → (início mudou, fim mudou, só deslocada)
        pause_sig: dict[str, str] = {}
        pause_roots: set[str] = set()                        # folhas cujas pausas mudaram
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
            flags = None if cancelled else _typed_dates(c, prev)
            if flags:
                touched[c.id] = flags
            completed_on = None
            if percent >= 100 and not cancelled:
                # sem data real informada, a conclusão vale a partir de hoje
                completed_on = c.completed_on or today
            leaf_target[c.id] = (percent, status, completed_on)
            ranges = _pause_ranges(c.id, current, active, today)
            pause_sig[c.id] = ";".join(f"{a.isoformat()}..{b.isoformat()}" for a, b in ranges)
            if prev and (prev.start or prev.due) and (prev.pause or "") != pause_sig[c.id]:
                pause_roots.add(c.id)
            engine_tasks.append(ScheduleTask(
                id=c.id, parent_id=c.parent_id, duration=c.duration or 0.0, calendar=c.calendar,
                percent=percent, predecessors=c.predecessors, start=c.start,
                finished_on=completed_on, cancelled=cancelled,
                fixed_start=carried.get(c.id, c.fixed_start),
                not_before=block_floor.get(c.id), pauses=ranges,
            ))

        # Datas digitadas à mão. O cálculo prévio (sem as edições) diz onde cada tarefa
        # estava — com a fração de dia, que a data mostrada no ClickUp não tem.
        edits: dict[str, _Edit] = {}
        block_roots = {leaf for sid in block_edits for leaf in _leaves_under(sid, current, parents)}
        before = (compute_schedule(engine_tasks, calendar, today, reschedule=True).results
                  if touched or pause_roots or block_roots else {})
        for task_id, (start_changed, due_changed, moved) in touched.items():
            percent = leaf_target[task_id][0]
            edit = _interpret_edit(current[task_id], start_changed, due_changed, moved, percent,
                                   before.get(task_id), calendar, today)
            edits[task_id] = edit
            if edit.problem:
                summary.warnings.append(f'"{current[task_id].name}": {edit.problem}')
            if edit.completed_on:
                leaf_target[task_id] = (percent, leaf_target[task_id][1], edit.completed_on)
        engine_tasks = [_apply_edit(t, edits.get(t.id), leaf_target) for t in engine_tasks]

        # Só a tarefa mexida e as que dependem dela são recalculadas; as demais ficam
        # com as datas de agora — fixadas só as que o cálculo moveria (com a fração de
        # dia preservada nas outras, que saem do motor iguais ao que já está gravado).
        date_scope: set[str] | None = None
        roots = set(edits) | pause_roots | block_roots
        if roots and not (from_top and start != list_start):   # projeto inteiro mudou de início
            affected = dependents_of(engine_tasks, roots)
            engine_tasks = [_pin_outside(t, affected, parents, current, before) for t in engine_tasks]
            date_scope = affected | _ancestors(affected, current) | summary_due_typed
            logger.info(
                f"Cronograma [{list_id}]: {len(edits)} data(s) mudada(s) à mão, {len(block_edits)} grupo(s) "
                f"movido(s), {len(pause_roots)} pausa(s) mudada(s) — {len(affected)} tarefa(s) a recalcular"
            )
        for task_id, edit in edits.items():
            logger.info(f'Cronograma [{list_id}]: "{current[task_id].name}" mudada à mão — {edit.describe()}')
        for sid, day in block_edits.items():
            logger.info(f'Cronograma [{list_id}]: grupo "{current[sid].name}" — não começa antes de {_iso(day)}')

        f_fixed = find_field(fields, FIELD_FIXED_START, "date")
        if not f_fixed and not dry_run and (block_edits or any(e.fixed_start for e in edits.values())):
            f_fixed = await self._create_fixed_start_field(list_id, summary)

        output = compute_schedule(engine_tasks, calendar, today, reschedule=True)
        summary.warnings.extend(_named(w, current) for w in output.warnings)
        notices = _start_conflicts(edits, current, output.results, calendar, today)
        notices += _block_notices(block_edits, current, parents, output.results, calendar, today)
        notices += [(sid, _SUMMARY_DUE_NOTICE.format(due=current[sid].due)) for sid in summary_due_typed]
        if from_top and start != list_start and top_id in output.results:
            shown = output.results[top_id].start
            if shown and shown < start:
                notices.append((top_id, _TOP_ROW_NOTICE.format(start=start, shown=shown)))
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
                [replace(t, percent=0.0, start=None, finished_on=None, fixed_start=None, not_before=None,
                         pinned=None) for t in engine_tasks],
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
                typed = (from_top and c.id == top_id) or c.id in block_edits or c.id in summary_due_typed
                plan = _plan_summary(c, result, names, f_percent, f_duration, dates_allowed, normalize=typed)
                if c.id in block_edits and f_fixed and block_edits[c.id] != c.fixed_start:
                    plan["fields"].append((f_fixed["id"], date_to_ms(block_edits[c.id])))
                    plan["log"]["inicio_fixado"] = [_iso(c.fixed_start), _iso(block_edits[c.id])]
            elif c.status_type == "closed":
                continue
            else:
                percent, status, completed_on = leaf_target[c.id]
                plan = _plan_leaf(c, result, percent, status, completed_on, names, f_percent, f_completion)
                _plan_edit(c, edits.get(c.id), result, plan, f_duration, f_fixed)
                moved_with_block = carried.get(c.id)
                if (moved_with_block and moved_with_block != c.fixed_start and f_fixed
                        and not (edits.get(c.id) and edits[c.id].fixed_start)):
                    plan["fields"].append((f_fixed["id"], date_to_ms(moved_with_block)))
                    plan["log"]["inicio_fixado"] = [_iso(c.fixed_start), _iso(moved_with_block)]
                if not dates_allowed:
                    _drop_dates(plan)
            extra = pause_plans.get(c.id)
            if extra:
                plan["fields"] += extra["fields"]
                plan["clear"] += extra["clear"]
                plan["log"].update(extra["log"])
            if plan["task"] or plan["fields"] or plan["clear"]:
                plans.append(plan)
                summary.changes.append({"task_id": c.id, "name": c.name, "changes": plan["log"]})
        summary.changed = len(plans)

        if dry_run:
            return

        failed: set[str] = set()
        written: dict[str, tuple[dict, dict | None]] = {}   # tarefa → (o que foi enviado, resposta do PUT)
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
        # Antes de cada lote, pergunta ao ClickUp o que mudou desde a leitura: uma tarefa que
        # alguém mexeu enquanto o motor calculava não é regravada — a execução seguinte (que o
        # webhook dessa edição dispara) trata a mudança como edição, em vez de a desfazer.
        for level in sorted(by_depth, reverse=True):
            plans_here = by_depth[level]
            for i in range(0, len(plans_here), _CHECK_EVERY):
                batch = plans_here[i:i + _CHECK_EVERY]
                changed_now = await self._changed_since(list_id, read_at_ms, current, {p["id"] for p in batch})
                for plan in batch:
                    if plan["id"] in changed_now:
                        failed.add(plan["id"])
                        logger.info(f'Cronograma [{list_id}]: "{plan["name"]}" mudou durante a execução — '
                                    "não regravada; fica para a próxima")
                summary.writes += sum(await asyncio.gather(*(apply(p) for p in batch if p["id"] not in changed_now)))

        for task_id, text in notices:
            try:
                await self._call(lambda t=task_id, x=text: self._clickup.create_comment(t, x, notify_all=False))
                summary.writes += 1
            except Exception as exc:  # noqa: BLE001 — o aviso não pode desfazer o cálculo
                summary.errors.append(f"{current[task_id].name}: comentário não publicado — {_describe(exc)}")

        final = await self._dates_after_writes(list_id, current, written, summary)
        await self._save_state(list_id, current, leaf_target, names, failed, final, previous, pause_sig)
        logger.info(
            f"Cronograma [{list_id}]: {summary.tasks} tarefas, {summary.changed} alteradas, "
            f"{summary.writes} gravações, {len(summary.errors)} erro(s)"
        )

    # ─── Gravação ────────────────────────────────────────────────────────────

    async def _apply(self, plan: dict, written: dict[str, tuple[dict, dict | None]]) -> int:
        writes = 0
        task_id = plan["id"]
        if plan["task"]:
            response = await self._call(lambda: self._clickup.update_task_fields(task_id, plan["task"]))
            written[task_id] = (plan["task"], response if isinstance(response, dict) else None)
            writes += 1
        for field_id, value in plan["fields"]:
            await self._call(lambda f=field_id, v=value: self._clickup.set_custom_field(task_id, f, v))
            writes += 1
        for field_id in plan["clear"]:
            await self._call(lambda f=field_id: self._clickup.clear_custom_field(task_id, f))
            writes += 1
        return writes

    async def _call(self, factory):
        """Executa uma chamada ao ClickUp com espera em 429 e nova tentativa em falha de rede
        ou erro 5xx (o ClickUp devolve 500/502 de vez em quando, e a execução inteira se perdia)."""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                result = await factory()
                await asyncio.sleep(_WRITE_PAUSE_SECONDS)
                return result
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if attempt == _MAX_ATTEMPTS or not (status == 429 or status >= 500):
                    raise
                if status == 429:
                    wait = rate_limit_wait(exc.response)
                    logger.warning(f"Cronograma: limite de requisições do ClickUp, aguardando {wait:.0f}s")
                else:
                    wait = _RETRY_DELAY_SECONDS * attempt
                    logger.warning(f"Cronograma: ClickUp respondeu {status}, nova tentativa em {wait:.0f}s")
                await asyncio.sleep(wait)
            except httpx.TransportError:
                if attempt == _MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(_RETRY_DELAY_SECONDS * attempt)
        raise RuntimeError("unreachable")

    async def _dates_after_writes(
        self, list_id: str, current: dict[str, _Current], written: dict[str, tuple[dict, dict | None]],
        summary: ScheduleRunSummary,
    ) -> dict[str, tuple[date | None, date | None]]:
        """Datas que ficaram em cada tarefa — é delas que a próxima execução parte para
        reconhecer uma data mexida à mão. Cada tarefa gravada tem três leituras: o que foi
        enviado, o que a resposta do PUT diz que o ClickUp guardou e a releitura no fim:
          - a resposta difere do enviado: o ClickUp guardou outra coisa, e é isso que fica
            (senão a diferença viraria uma edição fantasma na próxima execução);
          - a releitura difere numa data só e a outra ficou a antiga: o ClickUp aplicou a
            gravação pela metade (visto no ClickUp real, raro) — grava de novo;
          - a releitura difere de outro jeito: alguém mexeu na tarefa depois da gravação.
            Fica o que o motor gravou, e a próxima execução trata a diferença como edição —
            antes ela era tomada pelo "que o motor deixou" e desfeita."""
        final = {task_id: (c.start, c.due) for task_id, c in current.items()}
        if not written:
            return final
        try:
            after = _parse_tasks(await self._call(lambda: self._clickup.get_tasks(list_id, include_closed=True)))
        except Exception as exc:  # noqa: BLE001 — sem a releitura, fica o que foi guardado
            logger.warning(f"Cronograma [{list_id}]: releitura após gravar falhou — {exc}")
            after = {}
        for task_id, (put, response) in written.items():
            c = current[task_id]
            old = (c.start, c.due)
            sent = _dates_now(c, put)
            stored = _dates_in(response) or sent
            got = (after[task_id].start, after[task_id].due) if task_id in after else stored
            if stored != sent and _halfway(stored, sent, old):
                # a resposta do PUT já vem com uma das datas antigas (visto no ClickUp real)
                final[task_id] = await self._write_dates_again(task_id, put, sent, c, summary)
            elif stored != sent:
                final[task_id] = stored
                summary.warnings.append(
                    f'"{c.name}": o ClickUp ficou com {_iso(stored[0])}–{_iso(stored[1])} '
                    f"em vez de {_iso(sent[0])}–{_iso(sent[1])}")
            elif got in (sent, old):                   # gravado, ou a leitura ainda não o mostra
                final[task_id] = sent
            elif _halfway(got, sent, old):
                final[task_id] = await self._write_dates_again(task_id, put, sent, c, summary)
            else:
                final[task_id] = sent
                logger.info(f'Cronograma [{list_id}]: "{c.name}" mudou durante a execução '
                            f"({_iso(got[0])}–{_iso(got[1])}) — vale como edição à mão")
        return final

    async def _changed_since(self, list_id: str, since_ms: int, current: dict[str, _Current], ids: set[str]) -> set[str]:
        """Tarefas de `ids` que alguém alterou desde a leitura (datas, status, % ou duração)."""
        try:
            raw = await self._call(lambda: self._clickup.get_tasks(list_id, include_closed=True,
                                                                     date_updated_gt=since_ms))
        except Exception as exc:  # noqa: BLE001 — sem a checagem, grava como antes
            logger.warning(f"Cronograma [{list_id}]: checagem antes de gravar falhou — {exc}")
            return set()
        fresh = _parse_tasks(raw)
        return {
            task_id for task_id in ids & set(fresh)
            if _signature(fresh[task_id]) != _signature(current[task_id])
        }

    async def _write_dates_again(
        self, task_id: str, put: dict, sent: tuple, c: _Current, summary: ScheduleRunSummary,
    ) -> tuple[date | None, date | None]:
        dates = {k: v for k, v in put.items() if k in ("start_date", "start_date_time", "due_date", "due_date_time")}
        try:
            await self._call(lambda: self._clickup.update_task_fields(task_id, dates))
            task = await self._call(lambda: self._clickup.get_task(task_id))
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"{c.name}: datas não regravadas — {_describe(exc)}")
            return sent
        summary.writes += 1
        got = (_site(task.get("start_date")), _site(task.get("due_date")))
        if got != sent:
            summary.warnings.append(
                f'"{c.name}": o ClickUp ficou com {_iso(got[0])}–{_iso(got[1])} '
                f"em vez de {_iso(sent[0])}–{_iso(sent[1])}")
        else:
            logger.info(f'Cronograma: "{c.name}" — o ClickUp aplicou só uma das datas; regravada')
        return got

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

    async def _load_state(self, list_id: str) -> dict[str, _Prev]:
        rows = (await self._db.execute(
            select(ScheduleTaskState).where(ScheduleTaskState.list_id == list_id)
        )).scalars().all()
        return {row.task_id: _Prev(row.percent, row.is_done, row.start, row.due, row.pause) for row in rows}

    async def _save_state(
        self,
        list_id: str,
        current: dict[str, _Current],
        leaf_target: dict[str, tuple[float, str, date | None]],
        names: StatusNames,
        failed: set[str],
        final: dict[str, tuple[date | None, date | None]],
        previous: dict[str, _Prev],
        pause_sig: dict[str, str] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # os resumos também: é pelas datas deles que se reconhece um grupo movido à mão
        # (e, na primeira linha, o início do projeto)
        for task_id, c in current.items():
            if task_id in leaf_target or task_id in failed:
                continue
            start, due = final[task_id]
            values = {"list_id": list_id, "percent": c.percent, "is_done": False,
                      "start": start, "due": due, "updated_at": now}
            stmt = sqlite_insert(ScheduleTaskState).values(task_id=task_id, **values)
            await self._db.execute(stmt.on_conflict_do_update(index_elements=["task_id"], set_=values))
        for task_id, (percent, status, _) in leaf_target.items():
            c = current[task_id]
            start, due = final[task_id]
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
                      "start": start, "due": due, "pause": (pause_sig or {}).get(task_id) or None,
                      "updated_at": now}
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
            **_read_pause(custom),
        )
    return current


def _read_pause(custom: list[dict]) -> dict:
    pause, history, bad = read_task_pauses(custom, settings.schedule_utc_offset_hours)
    return {"pause": pause, "history": tuple(history), "history_bad": tuple(bad)}


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


def _sort_pauses(
    current: dict[str, _Current], fields: dict, calendar: WorkCalendar, today: date, summary: ScheduleRunSummary,
) -> tuple[dict[str, Pause], dict[str, dict]]:
    """(pausas que valem no cálculo, gravações de arquivamento). A pausa cujo "Pausa até"
    já passou vai para o "Histórico de pausas" (juntando-se a uma contígua) e os três
    campos da pausa ficam limpos para a próxima. Lista sem os campos de pausa: nada."""
    active: dict[str, Pause] = {}
    plans: dict[str, dict] = {}
    if not all(fields.values()):
        return active, plans
    f_from, f_until, f_reason, f_history = (fields[n]["id"] for n in (
        FIELD_PAUSE_FROM, FIELD_PAUSE_UNTIL, FIELD_PAUSE_REASON, FIELD_PAUSE_HISTORY))
    for c in current.values():
        if c.history_bad:
            summary.warnings.append(
                f'"{c.name}": linha(s) do histórico de pausas que não deu para ler — {"; ".join(c.history_bad)}')
        pause = c.pause
        if not pause:
            continue
        if pause.end and pause.end < pause.start:
            summary.warnings.append(f'"{c.name}": "Pausa até" antes de "Pausa de" — a pausa foi ignorada')
            continue
        if pause.end and pause.end < today:
            history = archive(list(c.history), pause, calendar)
            clear = [f_from, f_until] + ([f_reason] if pause.reason else [])
            plans[c.id] = {
                "fields": [(f_history, format_history(history, list(c.history_bad)))],
                "clear": clear,
                "log": {"pausa_arquivada": [None, f"{pause.start:%d/%m/%Y} – {pause.end:%d/%m/%Y}"]},
            }
            continue
        active[c.id] = pause
    return active, plans


def _pause_ranges(task_id: str, current: dict[str, _Current], active: dict[str, Pause], today: date):
    """Pausas que valem para uma tarefa-folha: a dela e as das tarefas-mãe acima dela."""
    pauses: list[Pause] = []
    seen: set[str] = set()
    node: str | None = task_id
    while node and node not in seen:
        seen.add(node)
        if node in active:
            pauses.append(active[node])
        node = current[node].parent_id if node in current else None
    return blocked_ranges(pauses, today)


def _top_task_id(raw_tasks: list[dict], current: dict[str, _Current]) -> str | None:
    """A primeira linha da lista: a disciplina criada primeiro — a primeira da planilha
    na importação. Não dá para usar o `orderindex`: o ClickUp muda esse número quando
    uma tarefa é editada, e a "primeira" passava a ser outra a cada gravação."""
    tops = [t for t in raw_tasks if current.get(str(t["id"])) and not current[str(t["id"])].parent_id]

    def created(task: dict) -> tuple[int, str]:
        try:
            return int(task.get("date_created") or 0), str(task["id"])
        except (TypeError, ValueError):
            return 0, str(task["id"])

    return str(min(tops, key=created)["id"]) if tops else None


def _project_start(
    list_start: date | None, top: _Current | None, prev_top: _Prev | None,
) -> tuple[date | None, bool]:
    """(início do projeto, veio da primeira linha?).

    O início digitado na primeira linha vale quando é novo — diferente do que o motor
    deixou nela — ou quando a lista ainda não tem data de início. Sem isso, vale o
    início da lista (as datas da primeira linha são calculadas a partir dele)."""
    typed = top.start if top else None
    if typed and prev_top and prev_top.start and typed != prev_top.start:
        return typed, True
    if list_start:
        return list_start, False
    if typed:
        return typed, True
    return None, False


def _ancestors(task_ids: set[str], current: dict[str, _Current]) -> set[str]:
    found: set[str] = set()
    for task_id in task_ids:
        parent = current[task_id].parent_id
        while parent and parent not in found:
            found.add(parent)
            parent = current[parent].parent_id
    return found


def _pin_outside(
    task: ScheduleTask, affected: set[str], parents: set, current: dict[str, _Current], before: dict,
) -> ScheduleTask:
    """Tarefa-folha fora do alcance da edição fica com as datas que já tem. Só precisa
    de ser fixada se o cálculo a moveria; as que ele deixaria iguais seguem calculadas,
    para as sucessoras partirem da posição exata (com a fração de dia)."""
    c = current[task.id]
    if task.id in parents or task.id in affected or task.cancelled or not (c.start and c.due):
        return task
    result = before.get(task.id)
    if result and (result.start, result.finish) == (c.start, c.due):
        return task
    return replace(task, pinned=(c.start, c.due))


def _typed_dates(c: _Current, prev: _Prev | None) -> tuple[bool, bool, bool] | None:
    """Data de uma tarefa-folha diferente da que o motor deixou nela = mexida à mão.
    Devolve (início mudou, vencimento mudou, as duas andaram juntas — só deslocada).

    Sem estado anterior com datas (tarefa nova, ou estado de antes deste recurso)
    nada conta como edição. Data apagada também não: o motor volta a preenchê-la."""
    if not prev or (prev.start is None and prev.due is None):
        return None
    start_changed = c.start is not None and c.start != prev.start
    due_changed = c.due is not None and c.due != prev.due
    if not (start_changed or due_changed):
        return None
    moved = False
    if start_changed and due_changed and c.start and c.due and prev.start and prev.due:
        moved = (c.due - c.start) == (prev.due - prev.start)
    return start_changed, due_changed, moved


def _interpret_edit(
    c: _Current, start_changed: bool, due_changed: bool, moved: bool, percent: float,
    before, calendar: WorkCalendar, today: date,
) -> _Edit:
    """O que a data digitada vira no cálculo:
      - não iniciada: o início vira "não começar antes de"; o vencimento vira a duração
        que faz a tarefa terminar nesse dia (contando de onde ela começa — inclusive a
        meio de um dia, quando a antecessora termina a meio); mover as duas datas com a
        mesma distância entre elas é só mudar de lugar e mantém a duração;
      - em andamento: o início já vale como início real; o vencimento vira a duração cujo
        restante (duração × (1 − %)), contado de hoje, termina nesse dia;
      - concluída: o vencimento vira a data real de conclusão."""
    if percent >= 100:
        return _Edit(start_changed, due_changed, completed_on=c.due if due_changed else None)
    fixed_start = c.start if start_changed and percent <= 0 else None
    duration, problem = None, None
    if due_changed and not moved and c.due:
        if c.start and c.due < c.start:
            problem = "vencimento antes do início — a duração não foi alterada"
        elif percent > 0:
            duration, problem = _duration_in_progress(c, c.due, percent, calendar, today)
        else:
            duration, problem = _duration_not_started(c, c.due, start_changed, before, calendar)
    return _Edit(start_changed, due_changed, fixed_start=fixed_start, duration=duration, problem=problem)


def _floor2(value: float) -> float:
    """Arredonda para baixo, a 2 casas: arredondar para cima podia empurrar o fim para o dia seguinte."""
    return math.floor(value * 100 + 1e-9) / 100


def _as_typed_duration(workdays: float, calendar_type: str, calendar: WorkCalendar) -> float:
    """Dias úteis → a unidade do campo "Duração (dias)" da tarefa. Numa tarefa "Corrido" o
    motor converte dias corridos em úteis (× dias_úteis_semana / 7); aqui faz-se o inverso,
    para o fim cair no dia digitado — antes saíam dias corridos inteiros e o fim, um dia depois."""
    if calendar_type == CAL_CORRIDO:
        return workdays * 7 / calendar.days_per_week
    return workdays


def _duration_not_started(c: _Current, due: date, start_changed: bool, before, calendar: WorkCalendar):
    if not c.start:
        return None, None
    begin = float(calendar.index_of(c.start))
    if not start_changed and before and before.start == c.start:
        begin = before.pos_start                      # começa a meio do dia: conta a fração
    days = _floor2(_as_typed_duration(calendar.end_position(due) - begin, c.calendar, calendar))
    if days <= 0:
        return None, "início e vencimento em dias de folga — a duração não foi alterada"
    return days, None


def _duration_in_progress(c: _Current, due: date, percent: float, calendar: WorkCalendar, today: date):
    remaining = calendar.end_position(due) - calendar.index_of(today)
    if remaining <= 0:
        return None, ("vencimento antes de hoje numa tarefa em andamento — a duração não foi alterada; "
                      "atualize o % (ou conclua a tarefa)")
    return _floor2(_as_typed_duration(remaining / (1 - percent / 100), c.calendar, calendar)), None


def _apply_edit(task: ScheduleTask, edit: _Edit | None, leaf_target: dict) -> ScheduleTask:
    if not edit:
        return task
    changes: dict = {}
    if edit.duration is not None:
        changes["duration"] = edit.duration
    if edit.fixed_start:
        changes["fixed_start"] = edit.fixed_start
    if edit.completed_on:
        changes["finished_on"] = leaf_target[task.id][2]
    return replace(task, **changes) if changes else task


def _start_conflicts(
    edits: dict[str, _Edit], current: dict[str, _Current], results: dict, calendar: WorkCalendar, today: date,
) -> list[tuple[str, str]]:
    """Início digitado numa tarefa: a data vence as antecessoras (decisão de 22/10/2026) e só
    não fica antes de hoje. Vira comentário quando ficou antes do fim de uma antecessora
    (alerta) ou quando já tinha passado (ajustado). Um início num dia de folga que só
    passou para o dia útil seguinte não é comentado."""
    notices: list[tuple[str, str]] = []
    for task_id, edit in edits.items():
        wanted, result = edit.fixed_start, results.get(task_id)
        if not wanted or not result or not result.start:
            continue
        first_workday = calendar.date_at(calendar.index_of(wanted))   # o próprio dia, ou o próximo útil
        if result.start > first_workday:
            notices.append((task_id, (
                f"Cronograma: o início em {wanted:%d/%m/%Y} já passou e a tarefa não foi iniciada. "
                f"Início ajustado para {result.start:%d/%m/%Y}."
            )))
            continue
        late = [
            (results[p].pos_finish, results[p].finish, current[p].name) for p in current[task_id].predecessors
            if p in results and results[p].finish and results[p].pos_finish > result.pos_start + 1e-9
        ]
        if late:
            _, finish, name = max(late)
            notices.append((task_id, (
                f"Cronograma: início em {result.start:%d/%m/%Y} mantido como digitado, antes do fim de "
                f'"{name}" ({finish:%d/%m/%Y}), de que esta tarefa depende.'
            )))
    return notices


def _leaves_under(task_id: str, current: dict[str, _Current], parents: set) -> list[str]:
    found, stack = [], [task_id]
    while stack:
        node = stack.pop()
        kids = [c.id for c in current.values() if c.parent_id == node]
        if not kids and node != task_id:
            found.append(node)
        stack.extend(kids)
    return found


def _block_floors(current: dict[str, _Current], floors: dict[str, date]) -> dict[str, date]:
    """"Não começar antes de" de cada tarefa: o maior "Início fixado" dos grupos acima dela."""
    out: dict[str, date] = {}
    for c in current.values():
        found: list[date] = []
        node, seen = c.parent_id, set()
        while node and node not in seen:
            seen.add(node)
            if node in floors:
                found.append(floors[node])
            node = current[node].parent_id if node in current else None
        if found:
            out[c.id] = max(found)
    return out


def _block_notices(
    block_edits: dict[str, date], current: dict[str, _Current], parents: set, results: dict,
    calendar: WorkCalendar, today: date,
) -> list[tuple[str, str]]:
    """Grupo movido que não pôde começar no dia digitado: diz no grupo o que o segurou."""
    notices: list[tuple[str, str]] = []
    for sid, wanted in block_edits.items():
        result = results.get(sid)
        if not result or not result.start or result.start <= calendar.date_at(calendar.index_of(wanted)):
            continue
        leaves = [leaf for leaf in _leaves_under(sid, current, parents) if leaf in results and results[leaf].start]
        first = current[min(leaves, key=lambda leaf: results[leaf].pos_start)] if leaves else None
        finishes = [
            (results[p].pos_finish, results[p].finish, current[p].name)
            for p in (first.predecessors if first else ()) if p in results and results[p].finish
        ]
        if calendar.index_of(wanted) < calendar.index_of(today):
            reason = f"{wanted:%d/%m/%Y} já passou"
        elif calendar.index_of(wanted) < 0:
            reason = f"o projeto começa em {calendar.first_workday:%d/%m/%Y}"
        elif first and finishes:
            _, finish, name = max(finishes)
            reason = f'"{first.name}" depende de "{name}", que termina em {finish:%d/%m/%Y}'
        else:
            reason = f"o primeiro dia útil possível é {result.start:%d/%m/%Y}"
        notices.append((sid, (
            f"Cronograma: as tarefas deste grupo não começam antes de {wanted:%d/%m/%Y} (campo "
            f'"Início fixado" do grupo). O grupo começa em {result.start:%d/%m/%Y}: {reason}.'
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


def _signature(c: _Current) -> tuple:
    """O que uma pessoa pode mudar numa tarefa e o motor também grava."""
    return c.start, c.due, c.status, c.percent, c.duration, c.fixed_start


def _dates_in(task: dict | None) -> tuple[date | None, date | None] | None:
    """Datas de uma tarefa devolvida pelo ClickUp (a resposta do PUT); None sem resposta."""
    if not task or not ("start_date" in task or "due_date" in task):
        return None
    return _site(task.get("start_date")), _site(task.get("due_date"))


def _halfway(got: tuple, sent: tuple, old: tuple) -> bool:
    """Releitura com uma das datas enviadas e a outra ainda a antiga."""
    return any(
        got[i] == old[i] != sent[i] and got[1 - i] == sent[1 - i]
        for i in (0, 1)
    )


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


def _plan_summary(
    c, result, names: StatusNames, f_percent, f_duration, dates_allowed: bool = True, normalize: bool = False,
) -> dict:
    plan = {"id": c.id, "name": c.name, "task": {}, "fields": [], "clear": [], "log": {}}
    if dates_allowed:
        _date_changes(c, result.start, result.finish, plan, normalize=normalize)
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
