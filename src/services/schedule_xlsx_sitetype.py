"""Leitura das planilhas em WBS: tipos de site de transmissão ("Transmitter Site Type 1–4 - Work
Plan", 2026-10-21 — uma aba "Site FM - Type N") e estúdios provinciais ("Provincial Studios Type
1–2", 2026-10-28 — uma aba por sala: STUDIO, CTP e NEWSROOM, cada uma numa lista). As duas têm
as mesmas colunas e a aba "Parameters".

A WBS vem em linhas com ID, tipo (Project/Stage/Task), nível e pai. No ClickUp:
    Project (nível 1)            → a própria lista (não vira tarefa)
    Stage de nível 2             → disciplina
    Stage de nível 3             → grupo
    Task de nível 2, 3 ou 4      → tarefa (de topo, na disciplina ou no grupo)
A coluna "Weight (%)" é o peso do item dentro do seu pai e vira o campo "Peso (%)".

As datas não vêm: o cronograma parte do início que alguém puser na primeira linha, como nas
outras listas. Mas a ordem das etapas, na planilha, só está nas datas de "Stage Start" (digitadas
à mão, sem antecessoras entre etapas) — então cada etapa passa a depender da anterior na planilha
quando esta começou antes (decisão de 2026-10-23); as que começam juntas (Obra Civil e Logística)
correm em paralelo. Para uma etapa começar num dia certo, preenche-se o "Início fixado" dela.
Nos estúdios não vale a cadeia de etapas: a ordem está nas datas de início digitadas de etapas e
também de grupos ("blocos"), que se entrelaçam — a Acoustic começa antes de a Obra Civil acabar
(espera o piso; rodapés e limpeza continuam), o acabamento da Civil espera as ripas da Acoustic.
Cada bloco espera a tarefa (ou tarefas) que, na planilha, termina por último antes de ele começar
(decisão de 2026-10-29). Nos sites isso não serve: lá as datas têm esperas de propósito (o
Equipment Installation só em 10/11, entrega de equipamento), que ficam no "Início fixado".

Os planos por equipe de um site ("Lubango TX Site - Work Plan by Team", 2026-10-30) seguem o padrão
dos estúdios: os grupos (a frente de cada equipe) têm início próprio, e a ordem está nesses blocos.
A regra dos blocos vale sempre que algum grupo tem "Stage Start"; os modelos Tipo 1–4, que só têm o
início das etapas, continuam com a cadeia. A coluna "Team" (frente: CIVIL, RADIATING… — uma ou
várias, separadas por ";") vira o campo "Frente".

Marcos de duração zero e peso zero que ninguém espera ("End of Work") não viram tarefas, como no
formato antigo dos estúdios.
"""
from __future__ import annotations

import re
import warnings
from datetime import date, datetime, time, timedelta

import openpyxl

from src.services.schedule_engine import CAL_CORRIDO, CAL_UTIL

SHEET_PREFIX = "Site FM - Type"
ROOMS = ("STUDIO", "CTP", "NEWSROOM")
_WBS_HEADER = ("ID", "Name", "Type", "WBS Level", "Parent ID")
_LEVEL_OF = {("Stage", 2): 1, ("Stage", 3): 2, ("Task", 2): 1, ("Task", 3): 2, ("Task", 4): 3}


def _is_wbs_sheet(sheet) -> bool:
    header = next(sheet.iter_rows(max_row=1, values_only=True), ())
    return tuple(str(v or "").strip() for v in header[:len(_WBS_HEADER)]) == _WBS_HEADER


def is_site_type_workbook(book) -> bool:
    """Planilha em WBS: um tipo de site ou um estúdio provincial com as abas das salas nesse formato."""
    if any(name.startswith(SHEET_PREFIX) for name in book.sheetnames):
        return True
    return all(room in book.sheetnames for room in ROOMS) and _is_wbs_sheet(book[ROOMS[0]])


def _sheet(book, room: str | None):
    if any(name.startswith(SHEET_PREFIX) for name in book.sheetnames):
        return next(book[name] for name in book.sheetnames if name.startswith(SHEET_PREFIX))
    room = (room or "").strip().upper()
    if room not in ROOMS:
        raise ValueError(f"planilha de estúdio: informe a sala ({', '.join(ROOMS)}) — cada uma vai para uma lista")
    return book[room]


def _block_links(rows, col, kinds) -> dict[int, list[int]]:
    """Estúdios: cada bloco (etapa ou grupo com "Stage Start") espera a tarefa ou tarefas de fora
    dele que, na planilha, terminam por último até o início dele. O primeiro bloco não espera nada."""
    parent = {int(r[col["ID"]]): r[col["Parent ID"]] for r in rows}

    def under(row_id: int, block: int) -> bool:
        node, seen = parent.get(row_id), set()
        while node is not None and node not in seen:
            if int(node) == block:
                return True
            seen.add(node)
            node = parent.get(int(node))
        return False

    links: dict[int, list[int]] = {}
    for r in rows:
        block, start = int(r[col["ID"]]), r[col["Stage Start"]]
        if kinds[block][0] != "Stage" or not isinstance(start, datetime):
            continue
        done = [x for x in rows if kinds[int(x[col["ID"]])][0] == "Task" and not under(int(x[col["ID"]]), block)
                and isinstance(x[col["Finish"]], datetime) and x[col["Finish"]] <= start]
        if done:
            last = max(x[col["Finish"]] for x in done)
            links[block] = [int(x[col["ID"]]) for x in done if x[col["Finish"]] == last]
    return links


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _ids(value) -> list[int]:
    return [int(part) for part in re.split(r"[;,\s]+", str(value if value is not None else "")) if part.isdigit()]


def _resources(value) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split("&") if part.strip())


def _fronts(value) -> tuple[str, ...]:
    return tuple(part.strip().upper() for part in str(value or "").split(";") if part.strip())


# colunas de instruções do plano por equipe dos estúdios (2026-11-01) — vão para a descrição
NOTE_COLUMNS = ("Scope / Work Instructions", "Done When / Hold Point", "Next / Hands Over To")


# referência a uma célula de outra aba numa fórmula: STUDIO!H82, 'NEWSROOM'!$H$5
_ROOM_REF = re.compile(r"'?(" + "|".join(ROOMS) + r")'?!\$?[A-Z]+\$?(\d+)")


def _room_links(path: str, book, title: str, col: dict[str, int]) -> dict[int, tuple[tuple[str, int], ...]]:
    """Planos por equipe dos estúdios: o "Stage Start" de um bloco é uma fórmula com o fim das
    linhas que ele espera, às vezes noutra sala. Devolve, por ID, as (sala, ID) de fora."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        formulas = openpyxl.load_workbook(path)[title]
    links: dict[int, tuple[tuple[str, int], ...]] = {}
    for row in formulas.iter_rows(min_row=2):
        row_id, text = row[col["ID"]].value, row[col["Stage Start"]].value
        if row_id is None or not isinstance(text, str):
            continue
        refs = {(room, book[room].cell(int(line), col["ID"] + 1).value)
                for room, line in _ROOM_REF.findall(text) if room != title}
        if refs := {(room, int(ref)) for room, ref in refs if ref is not None}:
            links[int(row_id)] = tuple(sorted(refs))
    return links


def _notes(r, col: dict[str, int]) -> str | None:
    parts = [f"**{name}**\n{str(r[col[name]]).strip()}" for name in NOTE_COLUMNS
             if name in col and str(r[col[name]] or "").strip()]
    return "\n\n".join(parts) or None


def _clock(value) -> time | None:
    if isinstance(value, datetime):
        return value.time()
    return value if isinstance(value, time) else None


def _parameters(book) -> tuple[str, tuple[tuple[date, str], ...], tuple[str, ...]]:
    """Folga semanal, feriados e a jornada (linhas "jornada=" e "almoço=" da descrição da lista)."""
    mask, in_holidays = "0000001", False
    holidays: list[tuple[date, str]] = []
    start = lunch = None
    hours = lunch_hours = 0.0
    for row in book["Parameters"].iter_rows(values_only=True):
        label = str(row[0] or "").lower()
        if label.startswith("weekend pattern") and row[1]:
            mask = str(row[1]).strip()
        elif label.startswith("workday start"):
            start = _clock(row[1])
        elif label.startswith("working hours per day"):
            hours = float(row[1] or 0)
        elif label.startswith("lunch break start"):
            lunch = _clock(row[1])
        elif label.startswith("lunch break duration"):
            lunch_hours = float(row[1] or 0)
        elif label == "date":
            in_holidays = True
        elif in_holidays and (day := _as_date(row[0])):
            holidays.append((day, str(row[1] or "").strip()))
    lines: tuple[str, ...] = ()
    if start and hours:
        def at(clock: time, plus_hours: float) -> str:
            return (datetime.combine(date(2000, 1, 1), clock) + timedelta(hours=plus_hours)).strftime("%H:%M")
        lines = (f"jornada={start:%H:%M}-{at(start, hours + (lunch_hours if lunch else 0))}",)
        if lunch and lunch_hours:
            lines += (f"almoço={lunch:%H:%M}-{at(lunch, lunch_hours)}",)
    return mask, tuple(sorted(holidays)), lines


def load_site_type_schedule(path: str, room: str | None = None):
    from src.services.schedule_xlsx import XlsxSchedule, XlsxTask   # evita import circular

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # extensões de formatação que o openpyxl não lê
        book = openpyxl.load_workbook(path, data_only=True)
    sheet = _sheet(book, room)
    header = [str(c.value or "").strip() for c in sheet[1]]
    col = {name: header.index(name) for name in header if name}

    rows = [r for r in sheet.iter_rows(min_row=2, values_only=True) if r[col["ID"]] is not None]
    kinds = {int(r[col["ID"]]): (str(r[col["Type"]]), int(r[col["WBS Level"]])) for r in rows}
    key = lambda row_id: f"T:{row_id}"                                         # noqa: E731
    project = next((str(r[col["Name"]]) for r in rows if str(r[col["Type"]]) == "Project"), sheet.title)

    mask, holidays, lines = _parameters(book)
    stages = [r for r in rows if kinds[int(r[col["ID"]])] == ("Stage", 2)]
    stage_starts = {int(r[col["ID"]]): r[col["Stage Start"]] for r in stages
                    if isinstance(r[col["Stage Start"]], datetime)}
    # sites: cada etapa espera a anterior na planilha, se esta começou antes (as que começam juntas:
    # paralelo); estúdios: cada bloco espera a tarefa que termina logo antes dele
    chain: dict[int, list[int]] = {}
    group_starts = any(kinds[int(r[col["ID"]])] == ("Stage", 3) and isinstance(r[col["Stage Start"]], datetime)
                       for r in rows)
    if sheet.title in ROOMS or group_starts:
        chain = _block_links(rows, col, kinds)
    else:
        for before, after in zip(stages, stages[1:]):
            a, b = int(before[col["ID"]]), int(after[col["ID"]])
            if a in stage_starts and b in stage_starts and stage_starts[a] < stage_starts[b]:
                chain[b] = [a]
    waited = {p for r in rows for p in _ids(r[col["Predecessors"]])}
    outside = _room_links(path, book, sheet.title, col) if sheet.title in ROOMS else {}

    tasks: list[XlsxTask] = []
    for r in rows:
        row_id, name = int(r[col["ID"]]), str(r[col["Name"]] or "").strip()
        kind, level = kinds[row_id]
        if kind == "Project":
            continue
        if (kind == "Task" and not float(r[col["Task Duration (days)"]] or 0) and not float(r[col["Weight (%)"]] or 0)
                and row_id not in waited):
            continue                                   # marco final ("End of Work"): não vira tarefa
        if (kind, level) not in _LEVEL_OF:
            raise ValueError(f"{sheet.title} ID {row_id} ({name}): {kind} no nível {level} — "
                             "o ClickUp só tem 3 níveis abaixo da lista")
        parent = int(r[col["Parent ID"]]) if r[col["Parent ID"]] is not None else None
        parent_key = key(parent) if parent is not None and kinds.get(parent, ("", 0))[0] != "Project" else None
        is_summary = kind == "Stage"
        weight = r[col["Weight (%)"]]
        tasks.append(XlsxTask(
            key=key(row_id), name=name, level=_LEVEL_OF[(kind, level)], parent_key=parent_key,
            is_summary=is_summary,
            duration=0.0 if is_summary else float(r[col["Task Duration (days)"]] or 0.0),
            calendar=CAL_CORRIDO if str(r[col["Calendar"]] or "").strip().lower() == "calendar" else CAL_UTIL,
            percent=0.0,
            predecessors=tuple(key(p) for p in _ids(r[col["Predecessors"]]) + chain.get(row_id, []) if p != row_id),
            resources=_resources(r[col["Resource Names"]]),
            expected_start=None, expected_finish=None, expected_pos_start=None, expected_pos_finish=None,
            weight=round(float(weight) * 100, 2) if weight is not None else None,
            source_id=row_id, wbs=str(_LEVEL_OF[(kind, level)]),
            fronts=_fronts(r[col["Team"]]) if "Team" in col else (),
            notes=_notes(r, col),
            outside=outside.get(row_id, ()),
        ))

    return XlsxSchedule(province=sheet.title.replace(SHEET_PREFIX, "Type").strip(), project=project,
                        start=None, weekend_mask=mask, holidays=holidays, tasks=tuple(tasks), list_lines=lines)
