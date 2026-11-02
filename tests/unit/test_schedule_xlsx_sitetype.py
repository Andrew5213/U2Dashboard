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


# ─── Estúdios provinciais (Provincial Studios Type 1–2, 2026-10-28): mesmo formato, uma aba por sala ──

# ID, nome, tipo, nível, pai, antecessoras, duração, peso, início, fim (datas da planilha: só para
# achar a última tarefa da etapa anterior quando a seguinte se sobrepõe)
D = datetime
STUDIO_ROWS = [
    (1, "PMEx - RNA / STUDIO", "Project", 1, None, "", None, 1, D(2026, 10, 19, 8), D(2026, 11, 14, 12)),
    (2, "Civil Works", "Stage", 2, 1, "", None, 0.3, D(2026, 10, 19, 8), D(2026, 11, 3, 17)),
    (3, "Rubber Floor Installation", "Task", 3, 2, "", 1, 0.5, D(2026, 10, 27, 13), D(2026, 10, 28, 12)),
    (4, "Finishing & Cleaning (After Wall Battens)", "Stage", 3, 2, "", None, 0.5, D(2026, 10, 31, 13), D(2026, 11, 3, 17)),
    (5, "Skirting & Finishing Installation", "Task", 4, 4, "", 2, 0.6, D(2026, 10, 31, 13), D(2026, 11, 3, 12)),
    (6, "Room Cleaning & Handover", "Task", 4, 4, 5, 0.5, 0.4, D(2026, 11, 3, 13), D(2026, 11, 3, 17)),
    (7, "Studio Acoustic & Furniture Installation", "Stage", 2, 1, "", None, 0.6, D(2026, 10, 29, 8), D(2026, 11, 4, 17)),
    (8, "Wall Battens", "Task", 3, 7, "", 2.5, 0.5, D(2026, 10, 29, 8), D(2026, 10, 31, 12)),
    (9, "Furniture", "Stage", 3, 7, "", None, 0.5, D(2026, 11, 4, 8), D(2026, 11, 4, 17)),
    (10, "Announcer Desk", "Task", 4, 9, "", 1, 1, D(2026, 11, 4, 8), D(2026, 11, 4, 17)),
    (11, "Studio Equipment Installation", "Stage", 2, 1, "", None, 0.05, D(2026, 11, 5, 8), D(2026, 11, 7, 12)),
    (12, "Mixer", "Task", 3, 11, "", 1, 1, D(2026, 11, 5, 8), D(2026, 11, 5, 17)),
    (13, "Acceptance & Handover", "Task", 2, 1, 12, 2, 0.05, D(2026, 11, 12, 13), D(2026, 11, 14, 12)),
    (14, "End of Work", "Task", 2, 1, 13, 0, 0, D(2026, 11, 14, 12), D(2026, 11, 14, 12)),
]
STAGE_STARTS_STUDIO = {2: D(2026, 10, 19, 8), 4: D(2026, 10, 31, 12), 7: D(2026, 10, 29, 8),
                       9: D(2026, 11, 4, 8), 11: D(2026, 11, 5, 8)}


def _studio_workbook(path) -> str:
    book = openpyxl.Workbook()
    book.remove(book.active)
    col = {name: i for i, name in enumerate(HEADER)}
    for room in ("STUDIO", "CTP", "NEWSROOM"):
        sheet = book.create_sheet(room)
        sheet.append(HEADER)
        for task_id, name, kind, level, parent, preds, duration, weight, start, finish in STUDIO_ROWS:
            row = [None] * len(HEADER)
            row[col["ID"]], row[col["Name"]], row[col["Type"]] = task_id, name.replace("STUDIO", room), kind
            row[col["WBS Level"]], row[col["Parent ID"]], row[col["Predecessors"]] = level, parent, preds
            row[col["Calendar"]] = "Working" if kind == "Task" else None
            row[col["Task Duration (days)"]], row[col["Weight (%)"]] = duration, weight
            row[col["Start"]], row[col["Finish"]] = start, finish
            row[col["Stage Start"]] = STAGE_STARTS_STUDIO.get(task_id)
            sheet.append(row)
    params = book.create_sheet("Parameters")
    params.append(["Weekend pattern (Mon→Sun, 1 = day off)", "0000001"])
    params.append(["Workday start time", time(8, 0)])
    params.append(["Working hours per day", 8])
    file = path / "Provincial Studios Type 9 - Work Plan.xlsx"
    book.save(file)
    return str(file)


def test_a_studio_workbook_reads_the_room_asked_for(tmp_path):
    schedule = load_schedule([_studio_workbook(tmp_path)], room="CTP")

    assert schedule.project == "PMEx - RNA / CTP"
    assert [t.name for t in schedule.tasks][:2] == ["Civil Works", "Rubber Floor Installation"]
    assert schedule.list_lines == ("jornada=08:00-16:00",)            # sem almoço nos parâmetros


def test_a_studio_workbook_needs_the_room(tmp_path):
    with pytest.raises(ValueError, match="sala"):
        load_schedule([_studio_workbook(tmp_path)])


def test_each_studio_block_waits_for_the_task_that_ends_right_before_it(tmp_path):
    """Nos estúdios a ordem está nas datas de início digitadas das etapas E de grupos (blocos), que
    se entrelaçam: a Acoustic começa (29/10) antes de a Civil acabar (03/11) — espera o piso, não os
    rodapés e a limpeza (decisão de 2026-10-29); o acabamento da Civil espera as ripas da Acoustic; o
    mobiliário espera a limpeza da Civil. Cada bloco espera a tarefa que, na planilha, termina por
    último antes de ele começar."""
    schedule = load_schedule([_studio_workbook(tmp_path)], room="STUDIO")
    by_name = {t.name: t for t in schedule.tasks}
    key = lambda name: by_name[name].key                                    # noqa: E731

    assert by_name["Studio Acoustic & Furniture Installation"].predecessors == (key("Rubber Floor Installation"),)
    assert by_name["Finishing & Cleaning (After Wall Battens)"].predecessors == (key("Wall Battens"),)
    assert by_name["Furniture"].predecessors == (key("Room Cleaning & Handover"),)
    assert by_name["Studio Equipment Installation"].predecessors == (key("Announcer Desk"),)
    assert by_name["Civil Works"].predecessors == ()                        # o primeiro bloco


def test_the_end_of_work_milestone_is_left_out(tmp_path):
    schedule = load_schedule([_studio_workbook(tmp_path)], room="STUDIO")

    assert "End of Work" not in [t.name for t in schedule.tasks]       # duração 0 e peso 0
    assert "Acceptance & Handover" in [t.name for t in schedule.tasks]


# ─── Plano por equipe de um site (Lubango TX Site - Work Plan by Team, 2026-10-30) ──
# Mesmo formato dos tipos de site, mas os grupos (frentes de cada equipe) têm início próprio, como
# nos estúdios, e há a coluna "Team" com a frente (uma ou várias, separadas por ";").

def _team_workbook(path) -> str:
    rows = [
        # ID, nome, tipo, nível, pai, antecessoras, duração, peso, início, fim, Stage Start, Team
        (1, "Lubango TX Site", "Project", 1, None, "", None, 1, D(2026, 10, 26, 7), D(2026, 11, 14, 18), None, None),
        (2, "Civil Works", "Stage", 2, 1, "", None, 0.5, D(2026, 10, 26, 7), D(2026, 10, 27, 18), None, None),
        (3, "Shelter – PROEF Crew A", "Stage", 3, 2, "", None, 1, D(2026, 10, 26, 7), D(2026, 10, 27, 18),
         D(2026, 10, 26, 7), None),
        (4, "Rubber floor installation", "Task", 4, 3, "", 2, 1, D(2026, 10, 26, 7), D(2026, 10, 27, 18), None, "CIVIL"),
        (5, "Equipment Installation", "Stage", 2, 1, "", None, 0.5, D(2026, 10, 28, 7), D(2026, 10, 28, 18), None, None),
        (6, "Transmitter Room – U2 Crew", "Stage", 3, 5, "", None, 1, D(2026, 10, 28, 7), D(2026, 10, 28, 18),
         D(2026, 10, 28, 7), None),
        (7, "Racks", "Task", 4, 6, "", 1, 1, D(2026, 10, 28, 7), D(2026, 10, 28, 18), None, "EQUIPMENT; ELECTRICAL"),
    ]
    header = HEADER + ["Team"]
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Site FM - Type 1"
    sheet.append(header)
    col = {name: i for i, name in enumerate(header)}
    for task_id, name, kind, level, parent, preds, duration, weight, start, finish, stage_start, team in rows:
        row = [None] * len(header)
        row[col["ID"]], row[col["Name"]], row[col["Type"]] = task_id, name, kind
        row[col["WBS Level"]], row[col["Parent ID"]], row[col["Predecessors"]] = level, parent, preds
        row[col["Calendar"]] = "Working" if kind == "Task" else None
        row[col["Task Duration (days)"]], row[col["Weight (%)"]] = duration, weight
        row[col["Start"]], row[col["Finish"]], row[col["Stage Start"]] = start, finish, stage_start
        row[col["Team"]] = team
        sheet.append(row)
    params = book.create_sheet("Parameters")
    params.append(["Weekend pattern (Mon→Sun, 1 = day off)", "0000001"])
    file = path / "Lubango TX Site - Work Plan by Team.xlsx"
    book.save(file)
    return str(file)


def test_a_site_plan_with_group_starts_chains_its_blocks_like_the_studios(tmp_path):
    """Grupos com "Stage Start" próprio = a ordem está nos blocos: cada um espera a tarefa que, na
    planilha, termina logo antes dele (a regra dos estúdios). Os modelos Tipo 1–4, que só têm o
    início das etapas, continuam com a cadeia de etapas."""
    schedule = load_schedule([_team_workbook(tmp_path)])
    by_name = {t.name: t for t in schedule.tasks}

    assert by_name["Transmitter Room – U2 Crew"].predecessors == (by_name["Rubber floor installation"].key,)
    assert by_name["Equipment Installation"].predecessors == ()      # quem espera é o bloco, não a etapa


def test_the_team_column_becomes_the_fronts_of_each_task(tmp_path):
    schedule = load_schedule([_team_workbook(tmp_path)])
    by_name = {t.name: t for t in schedule.tasks}

    assert by_name["Rubber floor installation"].fronts == ("CIVIL",)
    assert by_name["Racks"].fronts == ("EQUIPMENT", "ELECTRICAL")
    assert by_name["Civil Works"].fronts == ()


def test_the_type_models_keep_the_stage_chain(tmp_path):
    schedule = load_schedule([_workbook(tmp_path, stage_starts=STAGE_STARTS)])
    assert all(t.fronts == () for t in schedule.tasks)               # sem coluna Team


NOTES = ("Scope / Work Instructions", "Done When / Hold Point", "Next / Hands Over To")


def test_the_instruction_columns_become_the_task_description(tmp_path):
    """Plano por equipe dos estúdios (2026-11-01): três colunas de instruções por linha, que vão
    para a descrição da tarefa no ClickUp — cada uma com o título da própria coluna."""
    file = _team_workbook(tmp_path)
    book = openpyxl.load_workbook(file)
    sheet = book.active
    header = [c.value for c in sheet[1]]
    for i, name in enumerate(NOTES, start=len(header) + 1):
        sheet.cell(1, i, name)
    racks = next(r for r in range(2, sheet.max_row + 1) if sheet.cell(r, 2).value == "Racks")
    sheet.cell(racks, len(header) + 1, "1. Fix the racks.\n2. Earth them.")
    sheet.cell(racks, len(header) + 2, "HOLD POINT – racks levelled")
    book.save(file)

    by_name = {t.name: t for t in load_schedule([file]).tasks}

    assert by_name["Racks"].notes == (
        "**Scope / Work Instructions**\n1. Fix the racks.\n2. Earth them.\n\n"
        "**Done When / Hold Point**\nHOLD POINT – racks levelled")
    assert by_name["Rubber floor installation"].notes is None      # colunas vazias = sem descrição


def test_without_the_instruction_columns_there_is_no_description(tmp_path):
    assert all(t.notes is None for t in load_schedule([_team_workbook(tmp_path)]).tasks)


def test_a_block_waiting_on_another_room_comes_from_the_stage_start_formula(tmp_path):
    """Plano por equipe dos estúdios (2026-11-02): o "Stage Start" é uma fórmula com o fim das
    linhas que o bloco espera — às vezes noutra sala (a COMAD que passa do estúdio para a redação,
    o SAT da CTP depois do do estúdio). Essas viram antecessoras noutra lista."""
    file = _studio_workbook(tmp_path)
    book = openpyxl.load_workbook(file)
    ctp = book["CTP"]
    col = HEADER.index("Stage Start") + 1
    row_of = {ctp.cell(r, 1).value: r for r in range(2, ctp.max_row + 1)}
    ctp.cell(row_of[11], col, "=IF(MOD(MAX(H11,STUDIO!H13),1)>0,MAX(H11,STUDIO!H13),0)")    # STUDIO linha 13 = ID 12
    ctp.cell(row_of[13], col, "=MAX('NEWSROOM'!$H$11,STUDIO!H14)")
    book.save(file)

    by_name = {t.name: t for t in load_schedule([file], room="CTP").tasks}

    assert by_name["Studio Equipment Installation"].outside == (("STUDIO", 12),)
    assert by_name["Acceptance & Handover"].outside == (("NEWSROOM", 10), ("STUDIO", 13))
    assert by_name["Mixer"].outside == ()
    studio = load_schedule([file], room="STUDIO")
    assert all(t.outside == () for t in studio.tasks)                  # a própria sala não conta
