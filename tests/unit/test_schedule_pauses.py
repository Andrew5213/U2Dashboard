"""Pausas: leitura e escrita do histórico, arquivamento com junção de pausas contíguas e o
efeito no motor (dias parados não contam como trabalho)."""
from datetime import date

from src.services.schedule_engine import ScheduleTask, WorkCalendar, compute_schedule
from src.services.schedule_pauses import Pause, archive, blocked_ranges, format_history, parse_history

CAL = WorkCalendar(start=date(2026, 10, 19), weekend_mask="0000001")      # folga só ao domingo


class TestHistory:
    def test_reads_one_pause_per_line_with_or_without_reason(self):
        pauses, bad = parse_history("05/11/2026 – 08/11/2026 · chuva\n10/11/2026 - 11/11/2026\n")
        assert bad == []
        assert [(p.start, p.end, p.reason) for p in pauses] == [
            (date(2026, 11, 5), date(2026, 11, 8), "chuva"), (date(2026, 11, 10), date(2026, 11, 11), "")]
        assert all(p.archived for p in pauses)

    def test_accepts_other_separators_people_type(self):
        pauses, bad = parse_history("1/12/2026 a 3/12/2026 - falta de material\n04/12/2026 até 05/12/2026: licença")
        assert bad == [] and [p.reason for p in pauses] == ["falta de material", "licença"]

    def test_unreadable_lines_are_reported_and_kept(self):
        pauses, bad = parse_history("parou uns dias\n05/11/2026 – 03/11/2026 · fim antes do início")
        assert pauses == [] and len(bad) == 2
        assert format_history([], bad).splitlines() == bad

    def test_round_trip(self):
        text = "05/11/2026 – 08/11/2026 · chuva"
        assert format_history(parse_history(text)[0]) == text


class TestArchive:
    def test_appends_in_date_order(self):
        old = [Pause(date(2026, 11, 20), date(2026, 11, 21), "licença", archived=True)]
        out = archive(old, Pause(date(2026, 11, 2), date(2026, 11, 4), "chuva"), CAL)
        assert [(p.start, p.end) for p in out] == [(date(2026, 11, 2), date(2026, 11, 4)), (date(2026, 11, 20), date(2026, 11, 21))]

    def test_contiguous_pause_is_merged(self):
        old = [Pause(date(2026, 10, 22), date(2026, 10, 23), "chuva", archived=True)]
        out = archive(old, Pause(date(2026, 10, 24), date(2026, 10, 27), "chuva"), CAL)
        assert [(p.start, p.end, p.reason) for p in out] == [(date(2026, 10, 22), date(2026, 10, 27), "chuva")]

    def test_only_rest_days_between_still_counts_as_contiguous(self):
        old = [Pause(date(2026, 10, 22), date(2026, 10, 24), "chuva", archived=True)]          # até sábado
        out = archive(old, Pause(date(2026, 10, 26), date(2026, 10, 27), "licença"), CAL)       # segunda
        assert len(out) == 1 and out[0].reason == "chuva; licença"

    def test_a_workday_in_between_keeps_them_apart(self):
        old = [Pause(date(2026, 10, 22), date(2026, 10, 23), "chuva", archived=True)]
        assert len(archive(old, Pause(date(2026, 10, 26), date(2026, 10, 27), ""), CAL)) == 2  # 24 é útil


class TestEngine:
    TODAY = date(2026, 10, 20)

    def _run(self, pauses=(), percent=0.0, start=None):
        tasks = [ScheduleTask("t", duration=5, pauses=pauses, percent=percent, start=start),
                 ScheduleTask("s", duration=1, predecessors=("t",))]
        out = compute_schedule(tasks, CAL, self.TODAY).results
        return (out["t"].start, out["t"].finish), out["s"].start

    def test_without_pause(self):
        assert self._run() == ((date(2026, 10, 20), date(2026, 10, 24)), date(2026, 10, 26))

    def test_pause_in_the_middle_pushes_the_end_and_the_successor(self):
        t, s = self._run(((date(2026, 10, 22), date(2026, 10, 23)),))
        assert t == (date(2026, 10, 20), date(2026, 10, 27)) and s == date(2026, 10, 28)

    def test_extending_the_pause_pushes_further(self):
        t, s = self._run(((date(2026, 10, 22), date(2026, 10, 27)),))
        assert t == (date(2026, 10, 20), date(2026, 10, 30)) and s == date(2026, 10, 31)

    def test_pause_at_the_start_delays_the_start(self):
        t, _ = self._run(((date(2026, 10, 20), date(2026, 10, 21)),))
        assert t == (date(2026, 10, 22), date(2026, 10, 27))

    def test_pause_on_rest_days_only_changes_nothing(self):
        assert self._run(((date(2026, 10, 25), date(2026, 10, 25)),))[0] == (date(2026, 10, 20), date(2026, 10, 24))

    def test_task_in_progress_does_the_rest_after_the_pause(self):
        t, _ = self._run(((date(2026, 10, 20), date(2026, 10, 22)),), percent=40, start=date(2026, 10, 16))
        assert t == (date(2026, 10, 16), date(2026, 10, 26))      # faltam 3 dias: 23, 24, 26

    def test_open_ended_pause_runs_until_today(self):
        ranges = blocked_ranges([Pause(date(2026, 10, 15), None, "licença")], self.TODAY)
        assert ranges == ((date(2026, 10, 15), self.TODAY),)
        t, _ = self._run(ranges)
        assert t == (date(2026, 10, 21), date(2026, 10, 26))      # recomeça amanhã

    def test_archived_pauses_do_not_block(self):
        assert blocked_ranges([Pause(date(2026, 10, 20), date(2026, 10, 21), "", archived=True)], self.TODAY) == ()
