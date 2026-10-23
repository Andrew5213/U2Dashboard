"""Motor de cálculo do cronograma de obra.

Porta fiel do modelo das planilhas PMEx (aba Cronograma): tudo é calculado em
"posição" — dias úteis decorridos desde o primeiro dia útil do projeto — e só
depois convertido em data. Sobre esse modelo entra a reprogramação pelo andamento
real, que a planilha não faz.

Módulo puro: não conhece ClickUp nem banco. Quem lê e grava é o ScheduleService.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, time, timedelta
from functools import cached_property

CAL_UTIL = "util"
CAL_CORRIDO = "corrido"

_EPS = 1e-9


@dataclass(frozen=True)
class WorkCalendar:
    """Calendário de trabalho. `weekend_mask` segue a planilha: 7 caracteres,
    segunda → domingo, "1" = folga ("0000001" = só domingo de folga)."""

    start: date
    weekend_mask: str = "0000001"
    holidays: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        mask = self.weekend_mask
        if len(mask) != 7 or set(mask) - {"0", "1"} or "0" not in mask:
            raise ValueError(f"weekend_mask inválida: {mask!r}")

    @property
    def days_per_week(self) -> int:
        return self.weekend_mask.count("0")

    def is_workday(self, day: date) -> bool:
        return self.weekend_mask[day.weekday()] == "0" and day not in self.holidays

    @cached_property
    def first_workday(self) -> date:
        day = self.start
        while not self.is_workday(day):
            day += timedelta(days=1)
        return day

    def date_at(self, index: int) -> date:
        """Data do dia útil de número `index` (0 = primeiro dia útil). Aceita
        índice negativo: tarefas concluídas antes do início oficial do projeto."""
        day = self.first_workday
        step = timedelta(days=1 if index >= 0 else -1)
        remaining = abs(index)
        while remaining:
            day += step
            if self.is_workday(day):
                remaining -= 1
        return day

    def index_of(self, day: date) -> int:
        """Posição do início de `day`: dias úteis em [primeiro dia útil, day).
        Num dia de folga devolve o índice do próximo dia útil."""
        first = self.first_workday
        if day >= first:
            return sum(
                1 for offset in range((day - first).days)
                if self.is_workday(first + timedelta(days=offset))
            )
        return -sum(
            1 for offset in range((first - day).days)
            if self.is_workday(day + timedelta(days=offset))
        )

    def end_position(self, day: date) -> int:
        """Posição ao fim de `day` (17h de um dia útil = início do seguinte)."""
        return self.index_of(day) + (1 if self.is_workday(day) else 0)


@dataclass(frozen=True)
class ScheduleTask:
    id: str
    parent_id: str | None = None
    duration: float = 0.0            # dias, como digitado
    calendar: str = CAL_UTIL         # CAL_UTIL | CAL_CORRIDO
    percent: float = 0.0             # 0..100
    predecessors: tuple[str, ...] = ()
    start: date | None = None        # início hoje gravado (vale como início real se em andamento)
    finished_on: date | None = None  # data real de conclusão
    cancelled: bool = False
    # "começa em" ("Início fixado"): numa tarefa não iniciada, o dia em que ela começa — vence
    # as antecessoras (como o "Must start on" do MS Project) e só não fica antes de hoje.
    # Num grupo/disciplina, o dia em que o bloco começa: as antecessoras de fora do bloco não
    # o seguram, as de dentro continuam a valer; vale o grupo fixado mais interno
    fixed_start: date | None = None
    # datas mantidas como estão (fora do alcance de uma edição) — as sucessoras
    # que forem recalculadas partem delas
    pinned: tuple[date, date] | None = None
    # pausas: (primeiro dia, último dia) em que a tarefa não anda — o trabalho que cairia
    # ali passa para depois; a duração não muda, o fim se afasta
    pauses: tuple[tuple[date, date], ...] = ()
    # "Peso (%)": peso da tarefa dentro do seu pai. Com peso em todos os filhos, o % do
    # resumo é a média ponderada por ele (como nas planilhas de tipos de site), não pela duração
    weight: float | None = None


@dataclass(frozen=True)
class ScheduleResult:
    id: str
    is_summary: bool
    start: date | None
    finish: date | None
    percent: float          # 0..100; nos resumos, média ponderada pela duração útil
    duration: float         # folha: como digitado; resumo: soma das durações das suas tarefas
    duration_util: float    # peso da tarefa (dias úteis)
    pos_start: float
    pos_finish: float


@dataclass(frozen=True)
class ScheduleOutput:
    results: dict[str, ScheduleResult]
    warnings: tuple[str, ...]


def useful_duration(duration: float, calendar_type: str, days_per_week: int) -> float:
    """Dias corridos → dias úteis, como a coluna M da planilha (cura do betão)."""
    if calendar_type == CAL_CORRIDO:
        return round(duration * days_per_week / 7, 4)
    return float(duration)


def compute_schedule(
    tasks: list[ScheduleTask],
    calendar: WorkCalendar,
    today: date,
    reschedule: bool = True,
) -> ScheduleOutput:
    """Calcula início/fim de todas as tarefas e o progresso dos resumos.

    reschedule=False reproduz a planilha (linha de base: o progresso não mexe nas
    datas). reschedule=True aplica o andamento real:
      - concluída: termina na data real e libera as sucessoras a partir dela;
      - em andamento: o que falta é executado a partir de hoje;
      - não iniciada: nunca começa antes de hoje.
    """
    by_id = {t.id: t for t in tasks}
    order = [t.id for t in tasks]
    graph = _LeafGraph(tasks)
    children, leaves_of, leaf_ids, preds = graph.children, graph.leaves_of, graph.leaf_ids, graph.preds
    warnings: list[str] = list(graph.warnings)

    ordered, cyclic = _topological_order(leaf_ids, preds)
    if cyclic:
        warnings.append("dependência circular entre: " + ", ".join(_ref(tid) for tid in cyclic))

    today_pos = calendar.index_of(today)
    anchors = {tid: a for tid in leaf_ids if (a := _fixed_block(tid, by_id))}
    pos_start: dict[str, float] = {}
    pos_finish: dict[str, float] = {}
    dates: dict[str, tuple[date | None, date | None]] = {}
    weights: dict[str, float] = {}

    for tid in ordered + cyclic:
        t = by_id[tid]
        m = 0.0 if t.cancelled else useful_duration(t.duration, t.calendar, calendar.days_per_week)
        weights[tid] = m
        pred_finish = max((pos_finish[p] for p in preds[tid] if p in pos_finish), default=0.0)
        p = min(max(t.percent, 0.0), 100.0) / 100

        if t.cancelled:
            n = max(0.0, pred_finish)
            pos_start[tid], pos_finish[tid] = n, n
            dates[tid] = (None, None)
            continue

        if t.pinned:
            start_day, finish_day = t.pinned
            n = float(calendar.index_of(start_day))
            o = max(float(calendar.end_position(finish_day)), n)
            pos_start[tid], pos_finish[tid] = n, o
            dates[tid] = (start_day, finish_day)
            continue

        blocks = _blocked_positions(calendar, t.pauses)
        if not reschedule or p <= 0:
            anchor = anchors.get(tid)
            if t.fixed_start:
                floor = float(calendar.index_of(t.fixed_start))
            elif anchor:
                block, block_day = anchor
                inside = [pos_finish[q] for q in preds[tid] if q in pos_finish and _is_under(q, block, by_id)]
                floor = max([float(calendar.index_of(block_day))] + inside)
            else:
                floor = max(0.0, pred_finish)
            n = max(floor, float(today_pos)) if reschedule else floor
            n, o = _work_through(n, m, blocks)
            start_day = calendar.date_at(math.floor(n + _EPS))
            finish_day = calendar.date_at(_finish_index(n, o))
        elif p >= 1:
            finish_day = t.finished_on or today
            o = float(calendar.end_position(finish_day))
            n = round(o - m, 6)
            planned_start = calendar.date_at(math.floor(n + _EPS))
            start_day = t.start if t.start and t.start <= finish_day else min(planned_start, finish_day)
        else:
            start_day = t.start if t.start and t.start <= today else today
            n = float(calendar.index_of(start_day))
            # o que falta é feito a partir de hoje, pulando as pausas que vierem
            _, rest_end = _work_through(float(today_pos), m * (1 - p), blocks)
            o = round(max(n, rest_end), 6)
            # aberta, nunca termina antes de hoje (um marco sem duração terminava ontem)
            finish_day = max(calendar.date_at(_finish_index(n, o)), start_day, calendar.date_at(today_pos))

        pos_start[tid], pos_finish[tid] = n, o
        dates[tid] = (start_day, finish_day)

    results: dict[str, ScheduleResult] = {}
    for tid in leaf_ids:
        t = by_id[tid]
        leaf_start, leaf_finish = dates[tid]
        results[tid] = ScheduleResult(
            id=tid, is_summary=False, start=leaf_start, finish=leaf_finish,
            percent=min(max(t.percent, 0.0), 100.0), duration=float(t.duration),
            duration_util=weights[tid], pos_start=pos_start[tid], pos_finish=pos_finish[tid],
        )

    def is_active(task_id: str) -> bool:
        return any(not by_id[leaf].cancelled for leaf in leaves_of(task_id))

    # do mais fundo para o topo: o % ponderado pelo peso usa o % dos filhos já calculado
    depth = {tid: _depth(tid, by_id) for tid in order}
    for tid in sorted((t for t in order if t in children), key=lambda t: -depth[t]):
        active = [leaf for leaf in leaves_of(tid) if not by_id[leaf].cancelled]
        if not active:
            results[tid] = ScheduleResult(tid, True, None, None, 0.0, 0.0, 0.0, 0.0, 0.0)
            continue
        total = sum(weights[leaf] for leaf in active)
        kids = [k for k in children[tid] if is_active(k)]
        percent = _combine(kids, active, by_id, weights, lambda k: results[k].percent)
        if percent >= 100 and any(results[leaf].percent < 100 for leaf in active):
            # tarefa sem duração não pesa, mas enquanto estiver aberta o resumo não fecha
            percent = 99.99
        first = min(pos_start[leaf] for leaf in active)
        last = max(pos_finish[leaf] for leaf in active)
        results[tid] = ScheduleResult(
            id=tid, is_summary=True,
            start=min(dates[leaf][0] for leaf in active),
            finish=max(dates[leaf][1] for leaf in active),
            percent=percent, duration=round(sum(float(by_id[leaf].duration) for leaf in active), 4),
            duration_util=total,
            pos_start=first, pos_finish=last,
        )

    return ScheduleOutput(results=results, warnings=tuple(warnings))


def _combine(kids: list[str], leaves: list[str], by_id: dict[str, ScheduleTask], util: dict[str, float],
             value) -> float:
    """Valor de um resumo a partir dos filhos: com "Peso (%)" em todos os filhos ativos, a
    média ponderada por ele (nível a nível); senão, pela duração útil das tarefas-folha."""
    kid_weight = sum(by_id[k].weight or 0.0 for k in kids)
    if kids and all(by_id[k].weight is not None for k in kids) and kid_weight > 0:
        return sum((by_id[k].weight or 0.0) * value(k) for k in kids) / kid_weight
    total = sum(util[leaf] for leaf in leaves)
    if total > 0:
        return sum(util[leaf] * value(leaf) for leaf in leaves) / total
    return sum(value(leaf) for leaf in leaves) / len(leaves)


def rollup(tasks: list[ScheduleTask], results: dict[str, ScheduleResult], leaf_values: dict[str, float]) -> dict[str, float]:
    """Leva um valor das tarefas-folha (ex.: % planejado) aos resumos pela mesma regra do % concluído."""
    by_id = {t.id: t for t in tasks}
    graph = _LeafGraph(tasks)
    util = {leaf: results[leaf].duration_util for leaf in graph.leaf_ids if leaf in results}
    values = {leaf: float(leaf_values.get(leaf, 0.0)) for leaf in graph.leaf_ids}

    def active_leaves(task_id: str) -> list[str]:
        return [leaf for leaf in graph.leaves_of(task_id) if not by_id[leaf].cancelled]

    for tid in sorted(graph.children, key=lambda t: -_depth(t, by_id)):
        leaves = active_leaves(tid)
        if not leaves:
            continue
        kids = [k for k in graph.children[tid] if active_leaves(k)]
        values[tid] = _combine(kids, leaves, by_id, util, lambda k: values.get(k, 0.0))
    return values


def project_weights(tasks: list[ScheduleTask]) -> dict[str, float]:
    """Peso de cada item no projeto inteiro (coluna "Project Weight" da planilha): o produto dos
    pesos do caminho, normalizados em cada nível, em %. Só onde todo o nível tem peso."""
    by_id = {t.id: t for t in tasks}
    children: dict[str | None, list[str]] = {}
    for t in tasks:
        parent = t.parent_id if t.parent_id in by_id else None
        children.setdefault(parent, []).append(t.id)
    out: dict[str, float] = {}

    def walk(parent: str | None, share: float) -> None:
        kids = children.get(parent, [])
        if not kids or any(by_id[k].weight is None for k in kids):
            return
        total = sum(by_id[k].weight or 0.0 for k in kids)
        if total <= 0:
            return
        for k in kids:
            out[k] = share * (by_id[k].weight or 0.0) / total
            walk(k, out[k])

    walk(None, 100.0)
    return out


@dataclass(frozen=True)
class WorkDay:
    """Jornada de trabalho (aba Parameters das planilhas): hora de início, horas trabalhadas
    por dia e o almoço, que não conta como trabalho."""
    start: time = time(8, 0)
    hours: float = 8.0
    lunch_start: time | None = time(12, 0)
    lunch_hours: float = 1.0


def clock_time(workday: WorkDay, fraction: float, end: bool) -> time:
    """Hora do dia para uma fração de dia útil, como as fórmulas da planilha: um início que
    cai na hora do almoço passa para depois dele; um fim exatamente no começo do almoço fica."""
    fraction = min(max(fraction, 0.0), 1.0)
    minutes = workday.start.hour * 60 + workday.start.minute + round(fraction * workday.hours * 60)
    if workday.lunch_start is not None and workday.lunch_hours:
        lunch = workday.lunch_start.hour * 60 + workday.lunch_start.minute
        if (minutes > lunch) if end else (minutes >= lunch):
            minutes += round(workday.lunch_hours * 60)
    minutes = min(minutes, 23 * 60 + 59)
    return time(minutes // 60, minutes % 60)


def _depth(task_id: str, by_id: dict[str, ScheduleTask]) -> int:
    depth, node, seen = 0, by_id[task_id].parent_id, {task_id}
    while node and node in by_id and node not in seen:
        seen.add(node)
        depth += 1
        node = by_id[node].parent_id
    return depth


def overall_percent(tasks: list[ScheduleTask], results: dict[str, ScheduleResult]) -> float | None:
    """% da lista inteira. Com peso em todas as linhas de topo ativas, a média ponderada
    pelo peso; senão, pela duração útil das tarefas-folha (como sempre foi)."""
    ids = {t.id for t in tasks}
    tops = [t for t in tasks if (not t.parent_id or t.parent_id not in ids)
            and t.id in results and results[t.id].start is not None]
    weight = sum(t.weight or 0.0 for t in tops)
    if tops and all(t.weight is not None for t in tops) and weight > 0:
        return sum((t.weight or 0.0) * results[t.id].percent for t in tops) / weight
    leaves = [r for r in results.values() if not r.is_summary and r.start]
    total = sum(r.duration_util for r in leaves)
    return sum(r.duration_util * r.percent for r in leaves) / total if total else None


def _fixed_block(task_id: str, by_id: dict[str, ScheduleTask]) -> tuple[str, date] | None:
    """O grupo/disciplina com "Início fixado" mais interno acima da tarefa, e a data."""
    node, seen = by_id[task_id].parent_id, set()
    while node and node in by_id and node not in seen:
        seen.add(node)
        day = by_id[node].fixed_start
        if day:
            return node, day
        node = by_id[node].parent_id
    return None


def _is_under(task_id: str, ancestor: str, by_id: dict[str, ScheduleTask]) -> bool:
    node, seen = by_id[task_id].parent_id, set()
    while node and node in by_id and node not in seen:
        if node == ancestor:
            return True
        seen.add(node)
        node = by_id[node].parent_id
    return False


class _LeafGraph:
    """Hierarquia e dependências expandidas até as folhas: depender de um resumo é
    depender de todas as tarefas dele; um resumo que depende de X faz todas as suas
    esperarem X."""

    def __init__(self, tasks: list[ScheduleTask]) -> None:
        by_id = {t.id: t for t in tasks}
        self.children: dict[str, list[str]] = {}
        for t in tasks:
            if t.parent_id and t.parent_id in by_id:
                self.children.setdefault(t.parent_id, []).append(t.id)
        self._leaf_cache: dict[str, tuple[str, ...]] = {}
        self.leaf_ids = [t.id for t in tasks if t.id not in self.children]
        self.warnings: list[str] = []
        self.preds: dict[str, set[str]] = {tid: set() for tid in self.leaf_ids}
        for t in tasks:
            for pred_id in t.predecessors:
                if pred_id not in by_id:
                    self.warnings.append(f"{_ref(t.id)}: antecessor {_ref(pred_id)} não está nesta lista — ignorado")
                    continue
                sources = set(self.leaves_of(pred_id))
                targets = set(self.leaves_of(t.id))
                if sources & targets:
                    self.warnings.append(
                        f"{_ref(t.id)}: dependência de {_ref(pred_id)} dentro do próprio grupo — ignorada")
                    continue
                for target in targets:
                    self.preds[target] |= sources

    def leaves_of(self, task_id: str) -> tuple[str, ...]:
        if task_id not in self._leaf_cache:
            kids = self.children.get(task_id)
            if not kids:
                self._leaf_cache[task_id] = (task_id,)
            else:
                self._leaf_cache[task_id] = tuple(leaf for kid in kids for leaf in self.leaves_of(kid))
        return self._leaf_cache[task_id]


def dependents_of(tasks: list[ScheduleTask], roots: set[str]) -> set[str]:
    """As tarefas-folha em `roots` mais todas as que esperam por elas, direta ou
    indiretamente (com as dependências de/para resumos já expandidas)."""
    graph = _LeafGraph(tasks)
    successors: dict[str, set[str]] = {}
    for leaf, sources in graph.preds.items():
        for source in sources:
            successors.setdefault(source, set()).add(leaf)
    reached = {root for root in roots if root in graph.preds}
    queue = list(reached)
    while queue:
        for nxt in successors.get(queue.pop(), ()):
            if nxt not in reached:
                reached.add(nxt)
                queue.append(nxt)
    return reached


def _blocked_positions(calendar: WorkCalendar, pauses: tuple[tuple[date, date], ...]) -> list[tuple[float, float]]:
    """Pausas em posições: [início do primeiro dia útil parado, fim do último)."""
    blocks = []
    for first, last in sorted(pauses):
        b0, b1 = float(calendar.index_of(first)), float(calendar.end_position(last))
        if b1 > b0:
            blocks.append((b0, b1))
    return blocks


def _work_through(start: float, work: float, blocks: list[tuple[float, float]]) -> tuple[float, float]:
    """(início, fim) de `work` dias úteis a partir de `start`, sem trabalhar nas pausas:
    começar dentro de uma pausa é começar quando ela acaba; uma pausa no meio empurra o
    resto do trabalho para depois dela."""
    for b0, b1 in blocks:
        if b0 <= start + _EPS < b1:
            start = b1
    position, remaining = start, work
    for b0, b1 in blocks:
        if b1 <= position + _EPS:
            continue
        if position + remaining <= b0 + _EPS:
            break
        remaining -= max(0.0, b0 - position)
        position = b1
    return start, round(position + remaining, 6)


def workdays_between(calendar: WorkCalendar, start: date, finish: date) -> int:
    """Dias úteis de `start` a `finish`, os dois inclusive — a duração de uma tarefa
    que ocupa esse intervalo."""
    return calendar.end_position(finish) - calendar.index_of(start)


def _ref(task_id: str) -> str:
    """Marca um id de tarefa numa mensagem, para quem exibe poder trocá-lo pelo nome."""
    return f"[[{task_id}]]"


def _finish_index(n: float, o: float) -> int:
    """Dia útil em que a tarefa termina. Terminar exatamente numa posição inteira
    é terminar às 17h do dia anterior, não às 8h do seguinte (coluna H da planilha)."""
    return max(math.ceil(o - _EPS) - 1, math.floor(n + _EPS))


def _topological_order(
    leaf_ids: list[str], preds: dict[str, set[str]]
) -> tuple[list[str], list[str]]:
    """Ordem de cálculo estável (segue a ordem de entrada). Devolve também as
    tarefas presas em ciclo, que são calculadas por último com o que houver."""
    pending = {tid: set(preds[tid]) for tid in leaf_ids}
    ordered: list[str] = []
    progressed = True
    while pending and progressed:
        progressed = False
        for tid in leaf_ids:
            if tid in pending and not pending[tid]:
                ordered.append(tid)
                del pending[tid]
                for remaining in pending.values():
                    remaining.discard(tid)
                progressed = True
    return ordered, [tid for tid in leaf_ids if tid in pending]


# ─── Coerência entre % concluído e status ────────────────────────────────────

@dataclass(frozen=True)
class StatusNames:
    open: str          # ex.: "planejando"
    in_progress: str   # ex.: "fazendo"
    done: str          # ex.: "complete"


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def reconcile_leaf(
    percent: float,
    status: str,
    status_type: str | None,
    prev_percent: float | None,
    prev_done: bool | None,
    names: StatusNames,
) -> tuple[float, str]:
    """Devolve (%, status) coerentes para uma tarefa-folha.

    Regra: 0% = aberta, 1–99% = em andamento, 100% = concluída. Quando os dois
    discordam, vence o que o utilizador acabou de mexer — por isso o estado
    anterior (prev_*) entra na decisão. Sem estado anterior, "concluída" vence.
    Status fora do trio (impedimento, revisão…) nunca é trocado, exceto ao
    chegar em 100%.
    """
    if status_type == "closed":  # cancelada: fora do cronograma
        return percent, status

    done = status_type == "done"
    was_complete = bool(prev_done) and prev_percent is not None and prev_percent >= 100

    if done and percent < 100:
        if was_complete:  # o utilizador baixou o % de uma tarefa concluída → reabre
            return percent, names.in_progress if percent > 0 else names.open
        return 100.0, status
    if not done and percent >= 100:
        if was_complete:  # o utilizador reabriu pelo status → o % não pode ficar em 100
            return (0.0 if _same(status, names.open) else 99.0), status
        return 100.0, names.done
    if not done and 0 < percent < 100 and _same(status, names.open):
        return percent, names.in_progress
    return percent, status


def summary_status(percent: float, status: str, status_type: str | None, names: StatusNames) -> str:
    """Status de um resumo, derivado do % calculado. Só troca se o status atual
    for um dos três automáticos — um resumo posto em "impedimento" fica como está."""
    if status_type == "closed":
        return status
    if not any(_same(status, auto) for auto in (names.open, names.in_progress, names.done)):
        return status
    if percent >= 100 - _EPS:
        return names.done
    return names.in_progress if percent > _EPS else names.open


def display_percent(percent: float) -> int:
    """% inteiro para gravar no ClickUp, sem arredondar para 0 ou 100 o que não é."""
    if percent >= 100 - _EPS:
        return 100
    if percent <= _EPS:
        return 0
    return min(99, max(1, round(percent)))
