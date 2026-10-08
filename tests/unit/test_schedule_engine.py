import json
from datetime import date
from pathlib import Path

import pytest

from src.services.schedule_engine import (
    CAL_CORRIDO,
    ScheduleTask,
    StatusNames,
    WorkCalendar,
    compute_schedule,
    display_percent,
    reconcile_leaf,
    summary_status,
    useful_duration,
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
        assert out.results["Obra Civil:1"].duration == pytest.approx(16)
        assert out.results["Logística:1"].percent == pytest.approx(100)
        assert out.results["Área Técnica:1"].duration == pytest.approx(31.7)

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
