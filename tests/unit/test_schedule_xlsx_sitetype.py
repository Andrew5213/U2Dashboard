"""Leitor das planilhas de tipos de site de transmissão (Transmitter Site Type 1–4, 2026-10-21)."""
from datetime import date, datetime, time

import openpyxl
import pytest

from src.services.schedule_engine import CAL_CORRIDO, CAL_UTIL
from src.services.schedule_xlsx import load_schedule

HEADER = ["ID", "Name", "Type", "WBS Level", "Parent ID", "Stage Duration (days)", "Start", "Finish",
          "Stage Start", "Predecessors", "Resource Names", "Calendar", "Working Duration (days)",
          "Start (pos)", "Finish (pos)", "% Complete", "Pause Start", "Pause Restart", "Pause Reason",
          "Paused Days", "% Planned", "Status", "Schedule Stage ID", "Stage Base", "Block Size",
          "Weight (%)", "Project Weight (%)", "Task Duration (days)"]

# ID, nome, tipo, nível, pai, antecessoras, recurso, calendário, duração, peso
ROWS = [
    (1, "Transmitter Site Type 9 - Work Plan", "Project", 1, None, "", None, None, None, 1),
    (2, "Transmitters Civil Works", "Stage", 2, 1, "", "PROEF", None, None, 0.6),
    (3, "Concrete Base for Generator", "Stage", 3, 2, "", "PROEF", None, None, 1),
    (4, "Soil Leveling and Compaction", "Task", 4, 3, "", "PROEF", "Working", 1, 0.25),
    (5, "Concrete Curing", "Task", 4, 3, 4, "PROEF", "Calendar", 14, 0.75),
    (6, "Electrical Installations", "Stage", 2, 1, "", "U2 BROADCAST & PROEF", None, None, 0.35),
    (7, "AC Distribution Panel", "Task", 3, 6, "", "U2 BROADCAST & PROEF", "Working", 0.5, 0.4),
    (8, "Surge Suppressor", "Task", 3, 6, 7, "U2 BROADCAST & PROEF", "Working", 0.5, 0.6),
    (9, "Acceptance & Handover", "Task", 2, 1, "5;8", "RNA", "Working", 1, 0.05),
]


def _workbook(path, rows=ROWS, stage_starts=None) -> str:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Site FM - Type 9"
    sheet.append(HEADER)
    col = {name: i for i, name in enumerate(HEADER)}
    for task_id, name, kind, level, parent, preds, resource, calendar, duration, weight in rows:
        row = [None] * len(HEADER)
        row[col["ID"]], row[col["Name"]], row[col["Type"]] = task_id, name, kind
        row[col["WBS Level"]], row[col["Parent ID"]], row[col["Predecessors"]] = level, parent, preds
        row[col["Resource Names"]], row[col["Calendar"]] = resource, calendar
        row[col["Task Duration (days)"]], row[col["Weight (%)"]] = duration, weight
        row[col["Start"]] = datetime(2026, 10, 13, 8)       # datas da planilha: ignoradas
        row[col["Stage Start"]] = (stage_starts or {}).get(task_id)
        sheet.append(row)
    params = book.create_sheet("Parameters")
    params.append(["Schedule Parameters"])
    params.append(["Project start (earliest Stage start)", datetime(2026, 10, 13, 8)])
    params.append(["Workday start time", time(8, 0)])
    params.append(["Working hours per day", 8])
    params.append(["Weekend pattern (Mon→Sun, 1 = day off)", "0000001"])
    params.append(["Lunch break start", time(12, 0)])
    params.append(["Lunch break duration (hours)", 1])
    params.append(["Holidays (non-working)"])
    params.append(["Date", "Description"])
    params.append([datetime(2026, 11, 2), "All Souls' Day"])
    params.append([datetime(2026, 11, 11), "National Independence Day"])
    file = path / "Transmitter Site Type 9 - Work Plan.xlsx"
    book.save(file)
    return str(file)


def test_stages_groups_and_tasks_become_the_three_clickup_levels(tmp_path):
    schedule = load_schedule([_workbook(tmp_path)])
    by_name = {t.name: t for t in schedule.tasks}

    assert [t.name for t in schedule.tasks] == [
        "Transmitters Civil Works", "Concrete Base for Generator", "Soil Leveling and Compaction",
        "Concrete Curing", "Electrical Installations", "AC Distribution Panel", "Surge Suppressor",
        "Acceptance & Handover",
    ]                                                       # a linha "Project" é a própria lista
    civil, group, soil = by_name["Transmitters Civil Works"], by_name["Concrete Base for Generator"], \
        by_name["Soil Leveling and Compaction"]
    assert (civil.level, civil.parent_key, civil.is_summary) == (1, None, True)
    assert (group.level, group.parent_key, group.is_summary) == (2, civil.key, True)
    assert (soil.level, soil.parent_key, soil.is_summary) == (3, group.key, False)
    ac = by_name["AC Distribution Panel"]
    assert (ac.level, ac.parent_key) == (2, by_name["Electrical Installations"].key)   # tarefa direto na etapa
    handover = by_name["Acceptance & Handover"]
    assert (handover.level, handover.parent_key, handover.is_summary) == (1, None, False)


def test_durations_calendar_dependencies_and_weights(tmp_path):
    schedule = load_schedule([_workbook(tmp_path)])
    by_name = {t.name: t for t in schedule.tasks}

    curing = by_name["Concrete Curing"]
    assert (curing.duration, curing.calendar) == (14, CAL_CORRIDO)
    assert by_name["Soil Leveling and Compaction"].calendar == CAL_UTIL
    assert curing.predecessors == (by_name["Soil Leveling and Compaction"].key,)
    assert set(by_name["Acceptance & Handover"].predecessors) == {curing.key, by_name["Surge Suppressor"].key}
    assert by_name["Transmitters Civil Works"].weight == 60          # Weight (%) 0,6 → 60
    assert by_name["Concrete Curing"].weight == 75
    assert by_name["Surge Suppressor"].resources == ("U2 BROADCAST", "PROEF")


def test_dates_are_left_out_and_the_calendar_comes_from_the_parameters(tmp_path):
    schedule = load_schedule([_workbook(tmp_path)])

    assert schedule.start is None
    assert schedule.weekend_mask == "0000001"
    assert [d for d, _ in schedule.holidays] == [date(2026, 11, 2), date(2026, 11, 11)]
    assert all(t.percent == 0 for t in schedule.tasks)


def test_a_fifth_level_is_refused(tmp_path):
    rows = ROWS + [(10, "Too deep", "Task", 5, 4, "", None, "Working", 1, 1)]
    with pytest.raises(ValueError, match="nível"):
        load_schedule([_workbook(tmp_path, rows)])


def test_ids_and_wbs_levels_come_along(tmp_path):
    """WBS = o nível no ClickUp, como o "WBS Level" da planilha sem a linha do projeto (2026-10-23)."""
    schedule = load_schedule([_workbook(tmp_path)])
    by_name = {t.name: t for t in schedule.tasks}

    assert by_name["Transmitters Civil Works"].source_id == 2
    assert by_name["Transmitters Civil Works"].wbs == "1"          # etapa (planilha: 2)
    assert by_name["Concrete Base for Generator"].wbs == "2"       # grupo (planilha: 3)
    assert by_name["Concrete Curing"].wbs == "3"                   # tarefa (planilha: 4)
    assert by_name["Surge Suppressor"].wbs == "2"                  # tarefa direto na etapa
    assert by_name["Acceptance & Handover"].wbs == "1"             # tarefa de topo
    assert by_name["Acceptance & Handover"].source_id == 9


def test_the_workday_goes_to_the_list_description(tmp_path):
    schedule = load_schedule([_workbook(tmp_path)])
    assert schedule.list_lines == ("jornada=08:00-17:00", "almoço=12:00-13:00")


STAGE_STARTS = {2: datetime(2026, 10, 13, 8), 6: datetime(2026, 11, 3, 9, 48)}


def test_each_stage_waits_for_the_one_that_started_before_it(tmp_path):
    rows = ROWS[:5] + [(10, "Logistics", "Stage", 2, 1, "", "PROEF", None, None, 0)] + ROWS[5:]
    starts = {**STAGE_STARTS, 10: datetime(2026, 10, 13, 8)}
    schedule = load_schedule([_workbook(tmp_path, rows, starts)])
    by_name = {t.name: t for t in schedule.tasks}

    # Logística começa junto com a Obra Civil: em paralelo, sem dependência entre as duas
    assert by_name["Logistics"].predecessors == ()
    # a Elétrica começa depois: espera a etapa anterior na planilha (a Logística)
    assert by_name["Electrical Installations"].predecessors == (by_name["Logistics"].key,)
