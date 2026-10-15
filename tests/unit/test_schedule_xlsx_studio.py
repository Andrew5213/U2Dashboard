"""Leitor das planilhas de estúdio: uma lista por sala, com disciplina → grupo → tarefa e os
marcos virando dependências."""
from datetime import datetime

import openpyxl
import pytest

from src.services.schedule_xlsx import load_schedule
from src.services.schedule_xlsx_studio import WEEKEND_MASK

HEADER = ["ID", "Nome", "Tipo", "Nível WBS", "ID Pai", "Duração (dias)", "Início", "Fim", "Antecessores", "Nomes dos Recursos"]


def _sheet(book, title, rows):
    ws = book.create_sheet(title)
    ws.append(HEADER)
    for row in rows:
        row_id, name, kind, level, parent, duration, start, preds, team = row
        ws.append([row_id, name, kind, level, parent, duration, start, None, preds, team])
    return ws


def _civil(path):
    """Obra Civil: STUDIO com 4 níveis (projeto → Civil Works → grupo → tarefa), um grupo
    de mobiliário e o marco final; CTP e NEWSROOM mínimos."""
    book = openpyxl.Workbook()
    book.remove(book.active)
    studio = _sheet(book, "STUDIO", [
        (1, "PMEx - RNA Teste / CT PRINCIPAL — Obra Civil", "Resumo", 1, None, None, None, None, "GATESAIR"),
        (2, "Civil Works", "Resumo", 2, 1, None, None, None, "PROEF"),
        (3, "Demolições e Remoções", "Resumo", 3, 2, None, None, None, "PROEF"),
        (4, "Remoção do Teto", "Task", 4, 3, 3, "=WORKDAY(DataInicio-1,1,Feriados)", None, "PROEF"),
        (5, "Paredes", "Resumo", 3, 2, None, None, None, "PROEF"),
        (6, "Pintura das Paredes", "Task", 4, 5, 2, "=WORKDAY(H4,1,Feriados)", 3, "PROEF"),
        (7, "Studio Acoustic & Furniture Installation", "Resumo", 2, 1, None, None, None, "U2 BROADCAST"),
        (8, "Studio Furniture Installation", "Resumo", 3, 7, None, None, None, "U2 BROADCAST"),
        (9, "Instalação Control Desk", "Task", 4, 8, 1, "=WORKDAY(H3,1,Feriados)", 2, "U2 BROADCAST"),
        (10, "Fim da Obra Civil", "Marco", 2, 1, 0, "=MAX(H2,H7)", "2;7", "PROEF & U2 BROADCAST"),
    ])
    studio["L1"], studio["M1"] = "Data de início do projeto", datetime(2026, 10, 19)
    studio["L4"], studio["M4"] = datetime(2026, 11, 2), "Dia dos Finados"
    for room in ("CTP", "NEWSROOM"):
        _sheet(book, room, [
            (1, f"PMEx - RNA Teste / {room} — Obra Civil", "Resumo", 1, None, None, None, None, "GATESAIR"),
            (2, "Limpeza", "Resumo", 2, 1, None, None, None, "PROEF"),
            (3, "Limpeza e Entrega da Sala", "Task", 3, 2, 1, "=WORKDAY(DataInicio-1,1,Feriados)", None, "PROEF"),
        ])
    book.save(path)


def _technical(path):
    book = openpyxl.Workbook()
    book.remove(book.active)
    _sheet(book, "STUDIO", [
        (1, "PMEx - RNA Teste / CT PRINCIPAL — Área Técnica", "Resumo", 1, None, None, None, None, "GATESAIR"),
        (2, "Marco externo — Obra Civil concluída: Studio Furniture Installation", "Marco", 2, 1, 0, "=Marco_STUDIO", None, "U2 BROADCAST"),
        (3, "Studio Equipment Installation", "Resumo", 2, 1, None, None, None, "U2 BROADCAST"),
        (4, "Instalação Computadores", "Task", 3, 3, 2, "=WORKDAY(H3,1,Feriados)", 2, "U2 BROADCAST"),
        (5, "SAT Accepting Tests", "Resumo", 2, 1, None, None, None, "U2 BROADCAST & RNA"),
        (6, "Inventory List", "Task", 3, 5, 1, "=WORKDAY(H4,1,Feriados)", 3, "U2 BROADCAST & RNA"),
        (7, "Aceitação & Transferência", "Task", 2, 1, 2, "=WORKDAY(H6,1,Feriados)", 5, "RNA"),
        (8, "End of Work", "Marco", 2, 1, 0, "=H8", 7, "GATESAIR"),
    ])
    for room in ("CTP", "NEWSROOM"):
        _sheet(book, room, [
            (1, f"PMEx - RNA Teste / {room} — Área Técnica", "Resumo", 1, None, None, None, None, "GATESAIR"),
            (2, "Marco externo — Obra Civil concluída: Limpeza e Entrega da Sala", "Marco", 2, 1, 0, "=Marco_X", None, "PROEF"),
            (3, "Equipment Installation", "Resumo", 2, 1, None, None, None, "U2 BROADCAST"),
            (4, "Instalação Switch", "Task", 3, 3, 2, "=WORKDAY(H3,1,Feriados)", 2, "U2 BROADCAST"),
        ])
    book.save(path)


@pytest.fixture
def files(tmp_path):
    civil = tmp_path / "PMEx_RNA_Teste_Studios_1_Obra_Civil.xlsx"
    technical = tmp_path / "PMEx_RNA_Teste_Studios_2_Area_Tecnica.xlsx"
    _civil(civil)
    _technical(technical)
    return [str(technical), str(civil)]                    # a ordem dos ficheiros não importa


@pytest.fixture
def schedule(files):
    return load_schedule(files, "STUDIO")


@pytest.fixture
def ctp(files):
    return load_schedule(files, "ctp")                      # a sala aceita minúsculas


def _by_name(schedule, room, name):
    return next(t for t in schedule.tasks if t.name == name)


class TestStructure:
    def test_three_levels_discipline_group_task(self, schedule):
        assert [t.name for t in schedule.tasks if t.level == 1] == ["Obra Civil", "Área Técnica"]
        demolicoes = _by_name(schedule, "STUDIO", "Demolições e Remoções")
        assert demolicoes.level == 2 and demolicoes.is_summary and demolicoes.parent_key == "Obra Civil"
        teto = _by_name(schedule, "STUDIO", "Remoção do Teto")
        assert teto.level == 3 and teto.parent_key == demolicoes.key and teto.duration == 3

    def test_wrapper_phases_project_rows_and_milestones_are_not_tasks(self, schedule):
        names = {t.name for t in schedule.tasks}
        assert "Civil Works" not in names and "Studio Acoustic & Furniture Installation" not in names
        assert not any(n.startswith("PMEx") or n.startswith("Marco externo") for n in names)
        assert "Fim da Obra Civil" not in names and "End of Work" not in names

    def test_task_directly_under_a_phase_sits_under_its_discipline(self, schedule):
        acceptance = _by_name(schedule, "STUDIO", "Aceitação & Transferência")
        assert acceptance.level == 2 and acceptance.parent_key == "Área Técnica" and not acceptance.is_summary

    def test_each_room_is_its_own_schedule(self, schedule, ctp):
        assert "Remoção do Teto" in {t.name for t in schedule.tasks}
        assert "Remoção do Teto" not in {t.name for t in ctp.tasks}
        assert {t.name for t in ctp.tasks} == {"Obra Civil", "Área Técnica", "Limpeza", "Limpeza e Entrega da Sala",
                                                "Equipment Installation", "Instalação Switch"}

    def test_room_is_required(self, files):
        with pytest.raises(ValueError, match="sala"):
            load_schedule(files)

    def test_calendar_teams_and_holidays(self, schedule):
        assert schedule.weekend_mask == WEEKEND_MASK == "0000011"
        assert [d.isoformat() for d, _ in schedule.holidays] == ["2026-11-02"]
        assert schedule.start.isoformat() == "2026-10-19"
        assert _by_name(schedule, "STUDIO", "Inventory List").resources == ("U2 BROADCAST", "RNA")
        assert all(t.percent == 0 for t in schedule.tasks)


class TestDependencies:
    def test_external_milestone_becomes_a_dependency_on_the_civil_task(self, schedule, ctp):
        computers = _by_name(schedule, "STUDIO", "Instalação Computadores")
        furniture = _by_name(schedule, "STUDIO", "Studio Furniture Installation")
        assert computers.predecessors == (furniture.key,)
        switch = _by_name(ctp, "CTP", "Instalação Switch")
        assert switch.predecessors == (_by_name(ctp, "CTP", "Limpeza e Entrega da Sala").key,)

    def test_dependency_on_a_flattened_phase_expands_to_its_groups(self, schedule):
        desk = _by_name(schedule, "STUDIO", "Instalação Control Desk")       # depende de "Civil Works"
        assert set(desk.predecessors) == {
            _by_name(schedule, "STUDIO", "Demolições e Remoções").key,
            _by_name(schedule, "STUDIO", "Paredes").key,
        }

    def test_group_dependency_is_kept(self, schedule):
        assert _by_name(schedule, "STUDIO", "Pintura das Paredes").predecessors == (
            _by_name(schedule, "STUDIO", "Demolições e Remoções").key,)


def test_inconsistent_predecessor_column_is_rejected(tmp_path):
    civil = tmp_path / "PMEx_RNA_Teste_Studios_1_Obra_Civil.xlsx"
    technical = tmp_path / "PMEx_RNA_Teste_Studios_2_Area_Tecnica.xlsx"
    _civil(civil)
    _technical(technical)
    book = openpyxl.load_workbook(civil)
    book["STUDIO"]["I7"] = 4                      # a fórmula de "Pintura das Paredes" usa H4 (ID 3)
    book.save(civil)
    with pytest.raises(ValueError, match="Antecessores"):
        load_schedule([str(civil), str(technical)], "STUDIO")
