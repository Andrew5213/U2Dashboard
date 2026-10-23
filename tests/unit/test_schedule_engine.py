import json
from datetime import date, time
from pathlib import Path

import pytest

from src.services.schedule_engine import (
    CAL_CORRIDO,
    ScheduleTask,
    StatusNames,
    WorkCalendar,
    compute_schedule,
    dependents_of,
    display_percent,
    WorkDay,
    clock_time,
    overall_percent,
    project_weights,
    reconcile_leaf,
    rollup,
    summary_status,
    useful_duration,
    workdays_between,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "lubango_schedule.json"
NAMES = StatusNames(open="planejando", in_progress="fazendo", done="complete")


@pytest.fixture(scope="module")
def lubango() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _calendar(data: dict) -> WorkCalendar:
    return WorkCalendar(
        start=date.fromisoformat(data["start"]),
        weekend_mask=data["weekend_mask"],
        holidays=frozenset(date.fromisoformat(day) for day, _ in data["holidays"]),
    )


def _tasks(data: dict) -> list[ScheduleTask]:
    return [
        ScheduleTask(
            id=row["key"], parent_id=row["parent_key"], duration=row["duration"],
            calendar=row["calendar"], percent=row["percent"],
            predecessors=tuple(row["predecessors"]),
        )
        for row in data["tasks"]
    ]


# ─── Paridade com a planilha (linha de base) ─────────────────────────────────

class TestSpreadsheetParity:
    def test_every_task_matches_the_spreadsheet(self, lubango):
        out = compute_schedule(_tasks(lubango), _calendar(lubango), date(2026, 10, 8), reschedule=False)
        assert out.warnings == ()
        leaves = [row for row in lubango["tasks"] if not row["is_summary"]]
        assert len(leaves) == 51
        for row in leaves:
            result = out.results[row["key"]]
            assert result.pos_start == pytest.approx(row["expected_pos_start"], abs=1e-6), row["name"]
            assert result.pos_finish == pytest.approx(row["expected_pos_finish"], abs=1e-6), row["name"]
            assert result.start.isoformat() == row["expected_start"], row["name"]
            assert result.finish.isoformat() == row["expected_finish"], row["name"]

    def test_summaries_span_their_tasks(self, lubango):
        out = compute_schedule(_tasks(lubango), _calendar(lubango), date(2026, 10, 8), reschedule=False)
        summaries = [row for row in lubango["tasks"] if row["is_summary"]]
        assert len(summaries) == 11
        for row in summaries:
            result = out.results[row["key"]]
            assert result.is_summary
            assert result.start.isoformat() == row["expected_start"], row["name"]
            assert result.finish.isoformat() == row["expected_finish"], row["name"]

    def test_summary_percent_is_weighted_by_useful_duration(self, lubango):
        out = compute_schedule(_tasks(lubango), _calendar(lubango), date(2026, 10, 8), reschedule=False)
        assert out.results["Obra Civil:1"].percent == pytest.approx(16 / 39 * 100)   # 41,03% na planilha
        assert out.results["Logística:1"].percent == pytest.approx(100)

    def test_summary_duration_is_the_sum_of_its_tasks(self, lubango):
        out = compute_schedule(_tasks(lubango), _calendar(lubango), date(2026, 10, 8), reschedule=False)
        rows = {row["key"]: row for row in lubango["tasks"]}

        def under(key, row):
            parent = row["parent_key"]
            while parent:
                if parent == key:
                    return True
                parent = rows[parent]["parent_key"]
            return False

        for key, row in rows.items():
            if row["is_summary"]:
                leaves = [r["duration"] for r in rows.values() if not r["is_summary"] and under(key, r)]
                assert out.results[key].duration == pytest.approx(sum(leaves)), row["name"]

    def test_summary_duration_counts_parallel_tasks_in_full(self):
        cal = WorkCalendar(start=date(2026, 10, 19), weekend_mask="0000011")
        tasks = [ScheduleTask(id="g"), ScheduleTask(id="a", parent_id="g", duration=3),
                 ScheduleTask(id="b", parent_id="g", duration=2),
                 ScheduleTask(id="c", parent_id="g", duration=4, cancelled=True)]
        result = compute_schedule(tasks, cal, date(2026, 10, 15)).results["g"]
        assert result.duration == 5                    # a e b em paralelo somam 5; a cancelada não conta
        assert (result.start, result.finish) == (date(2026, 10, 19), date(2026, 10, 21))

    def test_project_ends_on_the_spreadsheet_date(self, lubango):
        out = compute_schedule(_tasks(lubango), _calendar(lubango), date(2026, 10, 8), reschedule=False)
        assert max(r.finish for r in out.results.values()) == date(2026, 11, 28)


# ─── Calendário ──────────────────────────────────────────────────────────────

class TestWorkCalendar:
    CAL = WorkCalendar(date(2026, 10, 13), "0000001", frozenset({date(2026, 11, 2), date(2026, 11, 11)}))

    def test_saturday_works_sunday_does_not(self):
        assert self.CAL.is_workday(date(2026, 10, 17))
        assert not self.CAL.is_workday(date(2026, 10, 18))
        assert self.CAL.date_at(5) == date(2026, 10, 19)

    def test_skips_holidays(self):
        assert self.CAL.date_at(16) == date(2026, 10, 31)
        assert self.CAL.date_at(17) == date(2026, 11, 3)   # 01/11 domingo, 02/11 Finados

    def test_index_and_date_are_inverse(self):
        for index in range(-10, 45):
            assert self.CAL.index_of(self.CAL.date_at(index)) == index

    def test_day_off_maps_to_next_workday(self):
        assert self.CAL.index_of(date(2026, 10, 18)) == self.CAL.index_of(date(2026, 10, 19))
        assert self.CAL.end_position(date(2026, 10, 18)) == 5
        assert self.CAL.end_position(date(2026, 10, 17)) == 5

    def test_dates_before_the_project_start_are_negative(self):
        assert self.CAL.index_of(date(2026, 10, 8)) == -4     # qui, sex, sáb, seg
        assert self.CAL.date_at(-4) == date(2026, 10, 8)

    def test_start_on_a_day_off_moves_to_the_first_workday(self):
        cal = WorkCalendar(date(2026, 10, 18), "0000001")
        assert cal.first_workday == date(2026, 10, 19)

    def test_rejects_bad_mask(self):
        with pytest.raises(ValueError):
            WorkCalendar(date(2026, 1, 1), "1111111")
        with pytest.raises(ValueError):
            WorkCalendar(date(2026, 1, 1), "00001")

    def test_running_days_convert_to_working_days(self):
        assert useful_duration(14, CAL_CORRIDO, 6) == 12
        assert useful_duration(14, CAL_CORRIDO, 5) == 10
        assert useful_duration(0.25, "util", 6) == 0.25


# ─── Reprogramação pelo andamento real ───────────────────────────────────────

CAL = WorkCalendar(date(2026, 10, 13), "0000001")


def _run(tasks, today):
    return compute_schedule(tasks, CAL, today, reschedule=True).results


class TestReschedule:
    def test_before_the_project_starts_nothing_moves(self):
        r = _run([ScheduleTask("a", duration=2), ScheduleTask("b", duration=1, predecessors=("a",))], date(2026, 10, 8))
        assert (r["a"].start, r["a"].finish) == (date(2026, 10, 13), date(2026, 10, 14))
        assert (r["b"].start, r["b"].finish) == (date(2026, 10, 15), date(2026, 10, 15))

    def test_late_unstarted_task_is_pushed_to_today(self):
        r = _run([ScheduleTask("a", duration=2), ScheduleTask("b", duration=1, predecessors=("a",))], date(2026, 10, 20))
        assert (r["a"].start, r["a"].finish) == (date(2026, 10, 20), date(2026, 10, 21))
        assert r["b"].start == date(2026, 10, 22)

    def test_task_in_progress_finishes_the_remainder_from_today(self):
        tasks = [
            ScheduleTask("a", duration=4, percent=50, start=date(2026, 10, 13)),
            ScheduleTask("b", duration=1, predecessors=("a",)),
        ]
        r = _run(tasks, date(2026, 10, 20))
        assert r["a"].start == date(2026, 10, 13)            # início real preservado
        assert r["a"].finish == date(2026, 10, 21)           # faltam 2 dias: 20 e 21
        assert r["b"].start == date(2026, 10, 22)

    def test_task_in_progress_with_a_future_start_starts_today(self):
        r = _run([ScheduleTask("a", duration=2, percent=10, start=date(2026, 10, 30))], date(2026, 10, 20))
        assert r["a"].start == date(2026, 10, 20)

    def test_finishing_early_pulls_the_successor_forward_but_not_before_today(self):
        tasks = [
            ScheduleTask("a", duration=5, percent=100, finished_on=date(2026, 10, 14)),
            ScheduleTask("b", duration=1, predecessors=("a",)),
        ]
        r = _run(tasks, date(2026, 10, 16))
        assert r["a"].finish == date(2026, 10, 14)
        assert r["b"].start == date(2026, 10, 16)            # pela linha de base seria 19/10

    def test_finishing_late_pushes_the_successor(self):
        tasks = [
            ScheduleTask("a", duration=1, percent=100, finished_on=date(2026, 10, 21)),
            ScheduleTask("b", duration=1, predecessors=("a",)),
        ]
        r = _run(tasks, date(2026, 10, 15))
        assert r["b"].start == date(2026, 10, 22)

    def test_done_without_a_completion_date_uses_today(self):
        r = _run([ScheduleTask("a", duration=1, percent=100)], date(2026, 10, 8))
        assert r["a"].finish == date(2026, 10, 8)
        assert r["a"].start <= r["a"].finish

    def test_done_task_keeps_a_real_start_that_precedes_the_finish(self):
        task = ScheduleTask("a", duration=1, percent=100, start=date(2026, 10, 1), finished_on=date(2026, 10, 9))
        assert _run([task], date(2026, 10, 20))["a"].start == date(2026, 10, 1)

    def test_out_of_sequence_progress_is_accepted(self):
        # a sucessora terminou antes da antecessora, como a Logística em Lubango
        tasks = [
            ScheduleTask("pintura", duration=2),
            ScheduleTask("logistica", duration=1, percent=100, finished_on=date(2026, 10, 8), predecessors=("pintura",)),
        ]
        r = _run(tasks, date(2026, 10, 8))
        assert r["logistica"].finish == date(2026, 10, 8)
        assert r["pintura"].start == date(2026, 10, 13)

    def test_cancelled_task_does_not_delay_or_weigh(self):
        tasks = [
            ScheduleTask("grp"),
            ScheduleTask("a", parent_id="grp", duration=3, cancelled=True),
            ScheduleTask("b", parent_id="grp", duration=1, percent=100, finished_on=date(2026, 10, 13), predecessors=("a",)),
        ]
        r = _run(tasks, date(2026, 10, 13))
        assert r["a"].start is None
        assert r["grp"].percent == 100
        assert r["grp"].duration_util == 1


class TestDependencies:
    def test_dependency_on_a_summary_waits_for_all_its_tasks(self):
        tasks = [
            ScheduleTask("grp"),
            ScheduleTask("a", parent_id="grp", duration=1),
            ScheduleTask("b", parent_id="grp", duration=4),
            ScheduleTask("c", duration=1, predecessors=("grp",)),
        ]
        out = compute_schedule(tasks, CAL, date(2026, 10, 8), reschedule=False)
        assert out.results["c"].pos_start == 4

    def test_summary_dependency_applies_to_its_tasks(self):
        tasks = [
            ScheduleTask("x", duration=2),
            ScheduleTask("grp", predecessors=("x",)),
            ScheduleTask("a", parent_id="grp", duration=1),
        ]
        out = compute_schedule(tasks, CAL, date(2026, 10, 8), reschedule=False)
        assert out.results["a"].pos_start == 2

    def test_unknown_predecessor_is_reported_and_ignored(self):
        out = compute_schedule([ScheduleTask("a", duration=1, predecessors=("zz",))], CAL, date(2026, 10, 8), False)
        assert out.results["a"].pos_start == 0
        assert "zz" in out.warnings[0]

    def test_cycle_is_reported_and_still_scheduled(self):
        tasks = [
            ScheduleTask("a", duration=1, predecessors=("b",)),
            ScheduleTask("b", duration=1, predecessors=("a",)),
        ]
        out = compute_schedule(tasks, CAL, date(2026, 10, 8), reschedule=False)
        assert any("circular" in w for w in out.warnings)
        assert out.results["a"].start is not None and out.results["b"].start is not None

    def test_three_levels_roll_up(self):
        tasks = [
            ScheduleTask("n1"),
            ScheduleTask("n2", parent_id="n1"),
            ScheduleTask("a", parent_id="n2", duration=1, percent=100, finished_on=date(2026, 10, 13)),
            ScheduleTask("b", parent_id="n2", duration=3),
            ScheduleTask("leaf2", parent_id="n1", duration=4),
        ]
        r = _run(tasks, date(2026, 10, 13))
        assert r["n2"].percent == pytest.approx(25)
        assert r["n1"].percent == pytest.approx(12.5)
        assert r["n1"].start == date(2026, 10, 13)


class TestSummaryCompletion:
    def test_open_task_without_duration_keeps_the_summary_open(self):
        tasks = [
            ScheduleTask("grp"),
            ScheduleTask("a", parent_id="grp", duration=5, percent=100, finished_on=date(2026, 10, 13)),
            ScheduleTask("nova", parent_id="grp"),            # criada sem duração, 0%
        ]
        percent = _run(tasks, date(2026, 10, 13))["grp"].percent
        assert percent < 100
        assert display_percent(percent) == 99
        assert summary_status(percent, "fazendo", "custom", NAMES) == "fazendo"


class TestWeights:
    """Coluna "Weight (%)" das planilhas de tipos de site (2026-10-23): o % de um resumo é a
    média ponderada pelo peso de cada filho direto, nível a nível; sem peso, pela duração."""

    def test_summary_percent_follows_the_weights_of_its_children(self):
        tasks = [
            ScheduleTask("g"),
            ScheduleTask("a", parent_id="g", duration=1, percent=50, weight=80),
            ScheduleTask("b", parent_id="g", duration=9, percent=0, weight=20),
        ]
        assert _run(tasks, date(2026, 10, 13))["g"].percent == pytest.approx(40)    # pela duração: 5

    def test_weights_apply_level_by_level(self):
        tasks = [
            ScheduleTask("d", weight=100),
            ScheduleTask("g1", parent_id="d", weight=50),
            ScheduleTask("a", parent_id="g1", duration=1, percent=100, finished_on=date(2026, 10, 13), weight=100),
            ScheduleTask("g2", parent_id="d", weight=50),
            ScheduleTask("b", parent_id="g2", duration=1, weight=30),
            ScheduleTask("c", parent_id="g2", duration=20, weight=70),
        ]
        results = _run(tasks, date(2026, 10, 13))
        assert results["g1"].percent == pytest.approx(100)
        assert results["g2"].percent == pytest.approx(0)
        assert results["d"].percent == pytest.approx(50)            # pela duração seria 100/22

    def test_without_weights_the_duration_still_rules(self):
        tasks = [
            ScheduleTask("g"),
            ScheduleTask("a", parent_id="g", duration=1, percent=50),
            ScheduleTask("b", parent_id="g", duration=9, percent=0),
        ]
        assert _run(tasks, date(2026, 10, 13))["g"].percent == pytest.approx(5)

    def test_a_child_without_weight_falls_back_to_the_duration(self):
        tasks = [
            ScheduleTask("g"),
            ScheduleTask("a", parent_id="g", duration=1, percent=50, weight=80),
            ScheduleTask("b", parent_id="g", duration=9, percent=0),
        ]
        assert _run(tasks, date(2026, 10, 13))["g"].percent == pytest.approx(5)

    def test_cancelled_children_leave_the_weighting(self):
        tasks = [
            ScheduleTask("g"),
            ScheduleTask("a", parent_id="g", duration=1, percent=50, weight=50),
            ScheduleTask("b", parent_id="g", duration=1, weight=50, cancelled=True),
        ]
        assert _run(tasks, date(2026, 10, 13))["g"].percent == pytest.approx(50)

    def test_overall_percent_weights_the_top_level(self):
        tasks = [
            ScheduleTask("civil", weight=15),
            ScheduleTask("a", parent_id="civil", duration=30, percent=100, finished_on=date(2026, 10, 13), weight=100),
            ScheduleTask("handover", duration=1, weight=85),
        ]
        results = compute_schedule(tasks, WorkCalendar(start=date(2026, 10, 13)), date(2026, 10, 13)).results
        assert overall_percent(tasks, results) == pytest.approx(15)

    def test_overall_percent_without_weights_uses_the_durations(self):
        tasks = [
            ScheduleTask("civil"),
            ScheduleTask("a", parent_id="civil", duration=3, percent=100, finished_on=date(2026, 10, 13)),
            ScheduleTask("handover", duration=1),
        ]
        results = compute_schedule(tasks, WorkCalendar(start=date(2026, 10, 13)), date(2026, 10, 13)).results
        assert overall_percent(tasks, results) == pytest.approx(75)


class TestWorkDay:
    """Jornada da planilha (Parameters): 08:00–17:00, almoço 12:00–13:00, 8 h por dia; as
    durações fracionadas viram horas. Início que cai às 12:00 vai para 13:00; fim às 12:00 fica."""

    WD = WorkDay(start=time(8), hours=8, lunch_start=time(12), lunch_hours=1)

    def test_start_times_skip_the_lunch_break(self):
        assert clock_time(self.WD, 0, end=False) == time(8)
        assert clock_time(self.WD, 0.25, end=False) == time(10)
        assert clock_time(self.WD, 0.5, end=False) == time(13)
        assert clock_time(self.WD, 0.75, end=False) == time(15)

    def test_finish_times(self):
        assert clock_time(self.WD, 1, end=True) == time(17)
        assert clock_time(self.WD, 0.5, end=True) == time(12)
        assert clock_time(self.WD, 0.2, end=True) == time(9, 36)          # Cable Tray na planilha

    def test_without_a_lunch_break(self):
        wd = WorkDay(start=time(7), hours=10, lunch_start=None, lunch_hours=0)
        assert clock_time(wd, 0.5, end=False) == time(12)
        assert clock_time(wd, 1, end=True) == time(17)


class TestProjectWeightsAndRollup:
    def _tasks(self, **extra):
        return [
            ScheduleTask("d", weight=60),
            ScheduleTask("g1", parent_id="d", weight=25),
            ScheduleTask("a", parent_id="g1", duration=1, weight=100, **extra),
            ScheduleTask("g2", parent_id="d", weight=75),
            ScheduleTask("b", parent_id="g2", duration=1, weight=40),
            ScheduleTask("c", parent_id="g2", duration=3, weight=60),
            ScheduleTask("h", duration=1, weight=40),
        ]

    def test_project_weight_multiplies_the_weights_down_the_tree(self):
        weights = project_weights(self._tasks())
        assert weights == pytest.approx({"d": 60, "g1": 15, "a": 15, "g2": 45, "b": 18, "c": 27, "h": 40})

    def test_no_project_weight_where_a_level_has_no_weights(self):
        tasks = [ScheduleTask("d", weight=100), ScheduleTask("a", parent_id="d", duration=1)]
        assert project_weights(tasks) == {"d": 100}

    def test_rollup_follows_the_same_rule_as_the_percent(self):
        tasks = self._tasks()
        results = compute_schedule(tasks, WorkCalendar(start=date(2026, 10, 13)), date(2026, 10, 13)).results
        values = rollup(tasks, results, {"a": 100, "b": 50, "c": 0, "h": 0})
        assert values["g2"] == pytest.approx(20)             # 40% × 50
        assert values["d"] == pytest.approx(40)              # 25% × 100 + 75% × 20

    def test_rollup_without_weights_uses_the_duration(self):
        tasks = [ScheduleTask("g"), ScheduleTask("a", parent_id="g", duration=1),
                 ScheduleTask("b", parent_id="g", duration=3)]
        results = compute_schedule(tasks, WorkCalendar(start=date(2026, 10, 13)), date(2026, 10, 13)).results
        assert rollup(tasks, results, {"a": 100, "b": 0})["g"] == pytest.approx(25)


# ─── % concluído × status ────────────────────────────────────────────────────

class TestReconcile:
    def test_progress_moves_an_open_task_to_in_progress(self):
        assert reconcile_leaf(30, "planejando", "open", None, None, NAMES) == (30, "fazendo")

    def test_full_progress_completes_the_task(self):
        assert reconcile_leaf(100, "fazendo", "custom", 40, False, NAMES) == (100, "complete")

    def test_completing_by_status_sets_100(self):
        assert reconcile_leaf(40, "complete", "done", 40, False, NAMES) == (100, "complete")
        assert reconcile_leaf(0, "complete", "done", None, None, NAMES) == (100, "complete")

    def test_lowering_the_percent_reopens_a_completed_task(self):
        assert reconcile_leaf(60, "complete", "done", 100, True, NAMES) == (60, "fazendo")
        assert reconcile_leaf(0, "complete", "done", 100, True, NAMES) == (0, "planejando")

    def test_reopening_by_status_cannot_leave_100(self):
        assert reconcile_leaf(100, "fazendo", "custom", 100, True, NAMES) == (99, "fazendo")
        assert reconcile_leaf(100, "planejando", "open", 100, True, NAMES) == (0, "planejando")

    def test_other_statuses_are_left_alone(self):
        assert reconcile_leaf(30, "impedimento", "custom", 30, False, NAMES) == (30, "impedimento")
        assert reconcile_leaf(0, "fazendo", "custom", 0, False, NAMES) == (0, "fazendo")
        assert reconcile_leaf(50, "cancelled", "closed", 50, False, NAMES) == (50, "cancelled")

    def test_summary_status_follows_the_percent(self):
        assert summary_status(0, "fazendo", "custom", NAMES) == "planejando"
        assert summary_status(41, "planejando", "open", NAMES) == "fazendo"
        assert summary_status(100, "fazendo", "custom", NAMES) == "complete"
        assert summary_status(41, "impedimento", "custom", NAMES) == "impedimento"

    def test_display_percent_never_rounds_into_the_extremes(self):
        assert display_percent(0) == 0
        assert display_percent(0.2) == 1
        assert display_percent(41.03) == 41
        assert display_percent(99.7) == 99
        assert display_percent(100) == 100


# ─── Datas digitadas à mão: restrição de início, datas fixadas, dependentes ──

class TestManualDates:
    """Semana de segunda a sexta, projeto a começar na segunda 19/10/2026."""

    CAL = WorkCalendar(start=date(2026, 10, 19), weekend_mask="0000011")
    TODAY = date(2026, 10, 15)

    def _chain(self, **overrides):
        """g = grupo com a → b; c depende de b; e depende do grupo; d solta."""
        tasks = {
            "g": ScheduleTask(id="g"),
            "a": ScheduleTask(id="a", parent_id="g", duration=3),
            "b": ScheduleTask(id="b", parent_id="g", duration=2, predecessors=("a",)),
            "c": ScheduleTask(id="c", duration=1, predecessors=("b",)),
            "e": ScheduleTask(id="e", duration=1, predecessors=("g",)),
            "d": ScheduleTask(id="d", duration=2),
        }
        for task_id, changes in overrides.items():
            tasks[task_id] = ScheduleTask(**{**tasks[task_id].__dict__, **changes})
        return list(tasks.values())

    def _dates(self, tasks, task_id):
        result = compute_schedule(tasks, self.CAL, self.TODAY).results[task_id]
        return result.start, result.finish

    def test_without_constraints_the_chain_follows_the_dependencies(self):
        tasks = self._chain()
        assert self._dates(tasks, "a") == (date(2026, 10, 19), date(2026, 10, 21))
        assert self._dates(tasks, "b") == (date(2026, 10, 22), date(2026, 10, 23))
        assert self._dates(tasks, "c") == (date(2026, 10, 26), date(2026, 10, 26))

    # "Início fixado" num grupo (decisão de 2026-10-23): é a data de início do bloco, como numa
    # tarefa — as antecessoras de fora do grupo não o seguram; dentro dele a ordem continua

    def test_a_group_fixed_start_is_where_the_block_starts(self):
        tasks = self._chain(g={"fixed_start": date(2026, 10, 27)})
        assert self._dates(tasks, "a") == (date(2026, 10, 27), date(2026, 10, 29))
        assert self._dates(tasks, "b") == (date(2026, 10, 30), date(2026, 11, 2))   # depois de a
        assert self._dates(tasks, "c") == (date(2026, 11, 3), date(2026, 11, 3))    # as sucessoras seguem
        assert self._dates(tasks, "e") == (date(2026, 11, 3), date(2026, 11, 3))

    def test_a_group_fixed_start_beats_the_predecessors_from_outside(self):
        tasks = self._chain(g={"predecessors": ("d",), "fixed_start": date(2026, 10, 19)})   # d até 20
        assert self._dates(tasks, "a")[0] == date(2026, 10, 19)

    def test_without_it_the_group_waits_for_its_predecessor(self):
        tasks = self._chain(g={"predecessors": ("d",)})
        assert self._dates(tasks, "a")[0] == date(2026, 10, 21)

    def test_the_innermost_fixed_group_wins(self):
        tasks = [
            ScheduleTask(id="D", fixed_start=date(2026, 10, 26)),
            ScheduleTask(id="g", parent_id="D", fixed_start=date(2026, 11, 2)),
            ScheduleTask(id="a", parent_id="g", duration=1),
            ScheduleTask(id="h", parent_id="D", duration=1),
        ]
        assert self._dates(tasks, "a")[0] == date(2026, 11, 2)
        assert self._dates(tasks, "h")[0] == date(2026, 10, 26)

    def test_a_group_fixed_start_on_a_rest_day_starts_on_the_next_workday(self):
        tasks = self._chain(g={"fixed_start": date(2026, 10, 24)})       # sábado
        assert self._dates(tasks, "a") == (date(2026, 10, 26), date(2026, 10, 28))

    def test_a_group_fixed_start_in_the_past_moves_to_today(self):
        cal = WorkCalendar(start=date(2026, 10, 5), weekend_mask="0000011")
        tasks = self._chain(g={"fixed_start": date(2026, 10, 6)})
        assert compute_schedule(tasks, cal, date(2026, 10, 15)).results["a"].start == date(2026, 10, 15)

    def test_fixed_start_beats_the_predecessor(self):
        tasks = self._chain(b={"fixed_start": date(2026, 10, 20)})        # a termina 21
        assert self._dates(tasks, "b") == (date(2026, 10, 20), date(2026, 10, 21))
        assert self._dates(tasks, "c") == (date(2026, 10, 22), date(2026, 10, 22))

    def test_fixed_start_stays_when_the_predecessor_slips(self):
        tasks = self._chain(a={"duration": 6}, b={"fixed_start": date(2026, 10, 22)})   # a até 26
        assert self._dates(tasks, "b") == (date(2026, 10, 22), date(2026, 10, 23))

    def test_fixed_start_of_a_task_beats_the_one_of_its_group(self):
        tasks = self._chain(g={"fixed_start": date(2026, 10, 26)}, b={"fixed_start": date(2026, 10, 21)})
        assert self._dates(tasks, "b")[0] == date(2026, 10, 21)

    def test_fixed_start_on_a_rest_day_starts_on_the_next_workday(self):
        tasks = self._chain(d={"fixed_start": date(2026, 10, 24)})        # sábado
        assert self._dates(tasks, "d") == (date(2026, 10, 26), date(2026, 10, 27))

    def test_fixed_start_in_the_past_of_a_task_not_started_moves_to_today(self):
        cal = WorkCalendar(start=date(2026, 10, 5), weekend_mask="0000011")
        tasks = self._chain(d={"fixed_start": date(2026, 10, 6)})
        result = compute_schedule(tasks, cal, date(2026, 10, 15)).results["d"]
        assert result.start == date(2026, 10, 15)

    def test_fixed_start_is_ignored_once_the_task_started(self):
        tasks = self._chain(d={"fixed_start": date(2026, 11, 2), "percent": 50, "start": date(2026, 10, 14)})
        assert self._dates(tasks, "d")[0] == date(2026, 10, 14)

    def test_a_task_in_progress_with_no_work_left_does_not_end_in_the_past(self):
        """Marco sem duração posto "em andamento" (fuzz de 2026-10-22, Saurimo): terminava ontem."""
        tasks = self._chain(d={"duration": 0, "percent": 50, "start": date(2026, 10, 13)})
        cal = WorkCalendar(start=date(2026, 10, 5), weekend_mask="0000011")
        result = compute_schedule(tasks, cal, date(2026, 10, 15)).results["d"]
        assert result.finish == date(2026, 10, 15)

    def test_a_group_fixed_start_is_ignored_by_a_task_already_started(self):
        tasks = self._chain(g={"fixed_start": date(2026, 11, 2)}, a={"percent": 50, "start": date(2026, 10, 14)})
        assert self._dates(tasks, "a")[0] == date(2026, 10, 14)

    def test_pinned_task_keeps_its_dates_and_the_successors_start_from_them(self):
        tasks = self._chain(a={"pinned": (date(2026, 10, 19), date(2026, 10, 23))})
        assert self._dates(tasks, "a") == (date(2026, 10, 19), date(2026, 10, 23))
        assert self._dates(tasks, "b") == (date(2026, 10, 26), date(2026, 10, 27))
        assert self._dates(tasks, "c") == (date(2026, 10, 28), date(2026, 10, 28))

    def test_pinned_task_in_the_past_is_not_moved_to_today(self):
        tasks = self._chain(d={"pinned": (date(2026, 10, 1), date(2026, 10, 2))})
        assert self._dates(tasks, "d") == (date(2026, 10, 1), date(2026, 10, 2))

    def test_dependents_include_successors_through_groups(self):
        tasks = self._chain()
        assert dependents_of(tasks, {"a"}) == {"a", "b", "c", "e"}
        assert dependents_of(tasks, {"c"}) == {"c"}
        assert dependents_of(tasks, {"d"}) == {"d"}
        assert dependents_of(tasks, {"g"}) == set()          # só folhas entram

    def test_workdays_between_counts_both_ends_and_skips_rest_days(self):
        assert workdays_between(self.CAL, date(2026, 10, 19), date(2026, 10, 23)) == 5
        assert workdays_between(self.CAL, date(2026, 10, 23), date(2026, 10, 26)) == 2   # sex → seg
        assert workdays_between(self.CAL, date(2026, 10, 24), date(2026, 10, 25)) == 0   # fim de semana
