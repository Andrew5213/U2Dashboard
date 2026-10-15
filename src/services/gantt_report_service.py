"""PDF de Gantt de uma província: tabela de tarefas à esquerda e barras numa linha do
tempo à direita, em A4 paisagem.

Entram todas as listas da pasta que têm tarefas com datas. Nas listas de cronograma
(3 níveis) cada tarefa traz início e término calculados pelo motor; nas listas comuns
vale o que houver (início nativo e "Vencimento"), e a tarefa-mãe sem data própria
cobre o intervalo das filhas. Lista sem nenhuma data fica de fora e é citada no fim."""
import asyncio
import math
from datetime import date, datetime, timedelta

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.repositories.cache_repository import CacheRepository
from src.services.report_service import (
    BLUE, BLUE_BG, BLUE_TXT, DARK, GRAY_50, GRAY_200, GRAY_400, GRAY_600, GREEN, NAVY, RED, WHITE,
    _Report, _descendants, _fmt_progress, _is_schedule, _s,
)
from src.services.report_strings import get_strings
from src.services.translation import translate

_MONTHS = {
    "pt": ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
}

# geometria da página (A4 paisagem, mm)
_LEFT, _RIGHT, _BOTTOM = 10.0, 287.0, 196.0
_NAME_W, _DATE_W, _PCT_W = 78.0, 17.0, 11.0
_TIMELINE_X = _LEFT + _NAME_W + 2 * _DATE_W + _PCT_W
_TIMELINE_W = _RIGHT - _TIMELINE_X
_ROW_H, _LIST_H, _HEADER_H = 4.6, 5.6, 9.0

_WEEK_LABEL_W = 8.0             # largura de um rótulo "dd/mm" na linha das semanas

_TRACK = (191, 219, 254)        # barra planejada
_TRACK_LATE = (254, 202, 202)   # barra em atraso (parte não executada)


def _span(spans: list[tuple[date, date] | None]) -> tuple[date, date] | None:
    known = [s for s in spans if s]
    return (min(s[0] for s in known), max(s[1] for s in known)) if known else None


def build_gantt_rows(tasks: list, today: date, lang: str = "pt") -> list[dict]:
    """Linhas do Gantt de uma lista, na ordem da árvore. `tasks` são as linhas do cache
    (com subtarefas). Só entra quem tem intervalo: datas próprias ou de alguma filha."""
    by_id = {tk.task_id: tk for tk in tasks}
    children: dict[str, list] = {}
    for tk in tasks:
        if tk.parent_task_id in by_id:
            children.setdefault(tk.parent_task_id, []).append(tk)
    is_schedule = _is_schedule(tasks)

    spans: dict[str, tuple[date, date] | None] = {}

    def span_of(tk, depth: int = 0) -> tuple[date, date] | None:
        if tk.task_id in spans:
            return spans[tk.task_id]
        own = None
        if tk.due_date or tk.start_date:
            end = (tk.due_date or tk.start_date).date()
            start = min(tk.start_date.date(), end) if tk.start_date else end
            own = (start, end)
        kids = children.get(tk.task_id, []) if depth < 10 else []   # proteção contra ciclo no cache
        kid_spans = [span_of(kid, depth + 1) for kid in kids]
        spans[tk.task_id] = own or _span(kid_spans)
        return spans[tk.task_id]

    rows: list[dict] = []
    for root in tasks:
        if root.parent_task_id in by_id:
            continue
        for item, level in [(root, 0), *_descendants(root.task_id, children)]:
            span = span_of(item)
            if span is None:
                continue
            is_done = item.status_type in ("done", "closed")
            if is_schedule:
                progress = item.progress_pct
            else:
                progress = 100.0 if is_done else None
            rows.append({
                "name": translate(item.name, lang),
                "level": level,
                "is_summary": item.task_id in children,
                "start": span[0],
                "end": span[1],
                "progress_pct": progress,
                "status": translate(item.status, lang) if item.status else "",
                "duration_days": item.duration_days,
                "is_done": is_done,
                "is_overdue": span[1] < today and not is_done,
            })
    return rows


class _GanttReport(_Report):
    def __init__(self, data: dict) -> None:
        FPDF.__init__(self, orientation="L", unit="mm", format="A4")
        self.space_name = data["folder_name"]
        self.generated_at = data["generated_at"]
        self.lang = data.get("lang", "pt")
        self.t = get_strings(self.lang)
        self.set_auto_page_break(auto=False)
        self.set_margins(left=_LEFT, top=10, right=297 - _RIGHT)
        self._start: date = data["range_start"]
        self._end: date = data["range_end"]
        self._days = (self._end - self._start).days + 1
        self._today: date = data["today"]

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", size=7)
        self.set_text_color(*GRAY_400)
        self.set_xy(_LEFT, 5)
        self.cell(_RIGHT - _LEFT, 4, _s(f"{self.t['gantt_title']}  -  {self.space_name}"), align="L")
        self.set_xy(_LEFT, 5)
        self.cell(_RIGHT - _LEFT, 4, f"{self.generated_at} {self.t['utc_label']}", align="R")

    def footer(self) -> None:
        self.set_y(-10)
        self.set_font("Helvetica", size=7)
        self.set_text_color(*GRAY_400)
        self.cell(0, 4,
                  f"U2 Broadcast  -  {self.t['gantt_title']}  -  "
                  f"{self.t['footer_page']} {self.page_no()} {self.t['footer_of']} {{nb}}",
                  align="C")

    # ── escala ───────────────────────────────────────────────────────────────

    def _x(self, day: date) -> float:
        """Borda esquerda do dia na linha do tempo."""
        return _TIMELINE_X + (day - self._start).days * _TIMELINE_W / self._days

    def _mondays(self) -> list[date]:
        first = self._start + timedelta(days=(7 - self._start.weekday()) % 7)
        return [first + timedelta(weeks=i) for i in range(((self._end - first).days // 7) + 1)]

    def _week_width(self) -> float:
        return _TIMELINE_W / self._days * 7

    def _label_every(self) -> int:
        """De quantas em quantas semanas cabe o rótulo "dd/mm". Toda semana tem a sua
        linha na grade; só em cronogramas muito longos o rótulo salta semanas — e
        nunca de forma irregular."""
        return max(1, math.ceil(_WEEK_LABEL_W / self._week_width()))

    def _month_starts(self) -> list[date]:
        starts, day = [], self._start.replace(day=1)
        while day <= self._end:
            starts.append(day)
            day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
        return starts

    # ── blocos ───────────────────────────────────────────────────────────────

    def build_title(self, data: dict) -> None:
        t = self.t
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 297, 26, style="F")
        self.set_xy(_LEFT, 5)
        self.set_font("Helvetica", style="B", size=7)
        self.set_text_color(147, 197, 253)
        self.cell(0, 4, _s(t["gantt_eyebrow"]))
        self.set_xy(_LEFT, 9.5)
        self.set_font("Helvetica", style="B", size=16)
        self._set_text(WHITE)
        self.cell(0, 8, self._fit(data["folder_name"], 180))
        self.set_xy(_LEFT, 18.5)
        self.set_font("Helvetica", size=8)
        self.set_text_color(191, 219, 254)
        self.cell(0, 4, _s(t["gantt_meta"].format(
            start=data["first_day"].strftime("%d/%m/%Y"), end=data["last_day"].strftime("%d/%m/%Y"),
            n=data["total_tasks"], date=data["generated_at"])))
        self._legend(29.5)
        self.set_y(35)

    def _legend(self, y: float) -> None:
        t = self.t
        items = [
            (t["gantt_legend_planned"], _TRACK, None),
            (t["gantt_legend_progress"], _TRACK, BLUE),
            (t["gantt_legend_done"], GREEN, None),
            (t["gantt_legend_overdue"], _TRACK_LATE, RED),
            (t["gantt_legend_summary"], GRAY_600, None),
        ]
        x = _LEFT
        self.set_font("Helvetica", size=6.5)
        self._set_text(GRAY_600)
        for label, track, fill in items:
            self.set_fill_color(*track)
            self.rect(x, y + 0.6, 7, 2.2, style="F")
            if fill:
                self.set_fill_color(*fill)
                self.rect(x, y + 0.6, 3.5, 2.2, style="F")
            self.set_xy(x + 8, y)
            width = self.get_string_width(_s(label)) + 6
            self.cell(width, 3.4, _s(label))
            x += 8 + width
        self.set_draw_color(*RED)
        self.set_line_width(0.3)
        self.line(x + 1, y, x + 1, y + 3.4)
        self.set_xy(x + 2.5, y)
        self.cell(40, 3.4, _s(f"{t['gantt_today']} ({self._today.strftime('%d/%m/%Y')})"))

    def _table_head(self) -> None:
        t = self.t
        y = self.get_y()
        self.set_fill_color(*NAVY)
        self.rect(_LEFT, y, _RIGHT - _LEFT, _HEADER_H / 2, style="F")
        self.rect(_LEFT, y, _TIMELINE_X - _LEFT, _HEADER_H, style="F")
        self.set_fill_color(*BLUE_BG)
        self.rect(_TIMELINE_X, y + _HEADER_H / 2, _TIMELINE_W, _HEADER_H / 2, style="F")

        self.set_font("Helvetica", style="B", size=7)
        self._set_text(WHITE)
        x = _LEFT
        for label, width, align in ((t["col_task"], _NAME_W, "L"), (t["col_start"], _DATE_W, "C"),
                                    (t["col_end"], _DATE_W, "C"), ("%", _PCT_W, "C")):
            self.set_xy(x + (1.5 if align == "L" else 0), y)
            self.cell(width, _HEADER_H, _s(label), align=align)
            x += width

        # meses
        months = _MONTHS[self.lang]
        self.set_draw_color(*WHITE)
        self.set_line_width(0.2)
        for first in self._month_starts():
            last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            x0 = self._x(max(first, self._start))
            x1 = self._x(min(last, self._end) + timedelta(days=1))
            if first > self._start:
                self.line(x0, y, x0, y + _HEADER_H / 2)
            label = f"{months[first.month - 1]}/{first.year}" if x1 - x0 >= 14 else months[first.month - 1]
            if x1 - x0 >= 6:
                self.set_xy(x0, y)
                self.cell(x1 - x0, _HEADER_H / 2, label, align="C")

        # semanas: cada uma começa na segunda-feira e leva a data dela (dd/mm)
        self.set_font("Helvetica", size=5.5)
        self._set_text(BLUE_TXT)
        self.set_draw_color(*GRAY_400)
        self.set_line_width(0.1)
        step = self._label_every()
        for index, monday in enumerate(self._mondays()):
            x = self._x(monday)
            self.line(x, y + _HEADER_H / 2, x, y + _HEADER_H)
            if index % step == 0 and _RIGHT - x >= _WEEK_LABEL_W - 1:
                self.set_xy(x + 0.3, y + _HEADER_H / 2)
                self.cell(_WEEK_LABEL_W, _HEADER_H / 2, monday.strftime("%d/%m"), align="L")

        # hoje: só um marcador sobre a linha vermelha — a data vai na legenda, para
        # nenhum rótulo tapar o de uma semana
        if self._start <= self._today <= self._end:
            x_today = self._x(self._today) + _TIMELINE_W / self._days / 2
            self.set_fill_color(*RED)
            self.rect(x_today - 0.9, y + _HEADER_H - 1.1, 1.8, 1.1, style="F")
        self.set_y(y + _HEADER_H)

    def _grid(self, y: float, h: float) -> None:
        """Linhas verticais da grade e a linha de hoje, no trecho de uma linha."""
        self.set_draw_color(*GRAY_200)
        self.set_line_width(0.1)
        for mark in self._mondays():
            if self._start < mark <= self._end:
                self.line(self._x(mark), y, self._x(mark), y + h)
        if self._start <= self._today <= self._end:
            x_today = self._x(self._today) + _TIMELINE_W / self._days / 2
            self.set_draw_color(*RED)
            self.set_line_width(0.3)
            self.line(x_today, y, x_today, y + h)

    def _ensure_room(self, needed: float) -> None:
        if self.get_y() + needed > _BOTTOM:
            self.add_page()
            self.set_y(12)
            self._table_head()

    def _list_band(self, name: str) -> None:
        y = self.get_y()
        self.set_fill_color(*BLUE_BG)
        self.rect(_LEFT, y, _RIGHT - _LEFT, _LIST_H, style="F")
        self.set_fill_color(*NAVY)
        self.rect(_LEFT, y, 1.5, _LIST_H, style="F")
        self.set_font("Helvetica", style="B", size=7.5)
        self._set_text(BLUE_TXT)
        self.set_xy(_LEFT + 3, y)
        self.cell(_NAME_W, _LIST_H, self._fit(name.upper(), _TIMELINE_X - _LEFT - 5))
        self._grid(y, _LIST_H)
        self.set_y(y + _LIST_H)

    def _row(self, row: dict, index: int) -> None:
        y = self.get_y()
        is_summary, level = row["is_summary"], row["level"]
        if index % 2 == 0:
            self.set_fill_color(*GRAY_50)
            self.rect(_LEFT, y, _RIGHT - _LEFT, _ROW_H, style="F")

        if row["is_done"]:
            color = GRAY_400
        elif row["is_overdue"]:
            color = RED
        else:
            color = DARK if is_summary else GRAY_600
        style = "B" if is_summary else ""
        indent = 1.5 + 3.5 * level
        self.set_font("Helvetica", style=style, size=6.8)
        self._set_text(color)
        self.set_xy(_LEFT + indent, y)
        self.cell(_NAME_W - indent, _ROW_H, self._fit(row["name"], _NAME_W - indent - 1))
        self.set_font("Helvetica", style=style, size=6.2)
        x = _LEFT + _NAME_W
        pct = row["progress_pct"]
        for text, width in ((row["start"].strftime("%d/%m/%Y"), _DATE_W), (row["end"].strftime("%d/%m/%Y"), _DATE_W),
                            (_fmt_progress(pct) if pct is not None else "-", _PCT_W)):
            self.set_xy(x, y)
            self.cell(width, _ROW_H, text, align="C")
            x += width

        self._grid(y, _ROW_H)

        x0 = self._x(row["start"])
        x1 = max(self._x(row["end"] + timedelta(days=1)), x0 + 0.8)
        if is_summary:
            self.set_fill_color(*(GRAY_400 if row["is_done"] else GRAY_600))
            self.rect(x0, y + 1.4, x1 - x0, 1.2, style="F")
            self.rect(x0, y + 1.4, 0.5, 2.2, style="F")
            self.rect(x1 - 0.5, y + 1.4, 0.5, 2.2, style="F")
        else:
            bar_y, bar_h = y + 1.0, _ROW_H - 2.0
            done_share = 1.0 if row["is_done"] else min(max((pct or 0.0) / 100, 0.0), 1.0)
            self.set_fill_color(*(_TRACK_LATE if row["is_overdue"] else _TRACK))
            self.rect(x0, bar_y, x1 - x0, bar_h, style="F")
            if done_share > 0:
                self.set_fill_color(*(GREEN if row["is_done"] else RED if row["is_overdue"] else BLUE))
                self.rect(x0, bar_y, (x1 - x0) * done_share, bar_h, style="F")
        self.set_y(y + _ROW_H)

    def build_lists(self, lists: list[dict]) -> None:
        self._table_head()
        for lst in lists:
            # o nome da lista nunca fica sozinho no fim da página
            self._ensure_room(_LIST_H + _ROW_H)
            self._list_band(lst["name"])
            for index, row in enumerate(lst["rows"]):
                self._ensure_room(_ROW_H)
                self._row(row, index)
        self.set_draw_color(*GRAY_200)
        self.set_line_width(0.2)
        self.line(_LEFT, self.get_y(), _RIGHT, self.get_y())

    def build_notes(self, data: dict) -> None:
        notes = []
        if data["undated_lists"]:
            notes.append(self.t["gantt_undated_lists"].format(names=", ".join(data["undated_lists"])))
        notes.append(self.t["disc_footnote"].format(date=data["generated_at"]))
        self._ensure_room(4 + 4 * len(notes))
        self.ln(2)
        self.set_font("Helvetica", size=7)
        self._set_text(GRAY_400)
        for note in notes:
            self.set_x(_LEFT)
            self.multi_cell(_RIGHT - _LEFT, 4, _s(note))

    def build_empty(self, data: dict) -> None:
        self.ln(20)
        self.set_font("Helvetica", "I", size=10)
        self._set_text(GRAY_400)
        self.set_x(_LEFT)
        self.multi_cell(_RIGHT - _LEFT, 6, _s(self.t["gantt_no_dates"]), align="C")


class GanttReportService:
    """Gantt em PDF de uma província (pasta): todas as listas que têm tarefas com datas."""

    def __init__(self, db: AsyncSession) -> None:
        self._repo = CacheRepository(db)

    async def generate_pdf(self, folder_id: str, lang: str = "pt") -> bytes:
        data = await self._build_data(folder_id, lang)
        return await asyncio.to_thread(self._render_pdf, data)

    async def generate_xlsx(self, folder_id: str, lang: str = "pt") -> bytes:
        data = await self._build_data(folder_id, lang)
        return await asyncio.to_thread(render_gantt_xlsx, data)

    async def _build_data(self, folder_id: str, lang: str = "pt") -> dict:
        t = get_strings(lang)
        folder = await self._repo.get_folder_by_id(folder_id)
        if not folder:
            raise ValueError(f"Pasta {folder_id} nao encontrada no cache")

        now = datetime.utcnow()
        # "hoje" no fuso da obra, como no motor do cronograma
        today = (now + timedelta(hours=settings.schedule_utc_offset_hours)).date()

        lists, undated = [], []
        for lst in await self._repo.get_lists_with_metrics(folder_id):
            tasks = await self._repo.get_tasks_by_list(lst["list_id"], include_subtasks=True)
            rows = build_gantt_rows(tasks, today, lang)
            name = translate(lst["name"], lang)
            if rows:
                lists.append({"list_id": lst["list_id"], "name": name, "rows": rows})
            else:
                undated.append(name)

        all_rows = [row for lst in lists for row in lst["rows"]]
        first_day = min((row["start"] for row in all_rows), default=today)
        last_day = max((row["end"] for row in all_rows), default=today)
        return {
            "folder_name": folder.name,
            "generated_at": now.strftime("%d/%m/%Y" + t["at_time"] + "%H:%M"),
            "today": today,
            "lists": lists,
            "undated_lists": undated,
            "total_tasks": sum(1 for row in all_rows if not row["is_summary"]),
            "first_day": first_day,
            "last_day": last_day,
            # a linha do tempo vai de segunda a domingo, cobrindo o intervalo inteiro
            "range_start": first_day - timedelta(days=first_day.weekday()),
            "range_end": last_day + timedelta(days=6 - last_day.weekday()),
            "lang": lang,
        }

    @staticmethod
    def _render_pdf(data: dict) -> bytes:
        logger.debug(f"Gerando PDF de Gantt: {data['folder_name']}")
        pdf = _GanttReport(data)
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.build_title(data)
        if data["lists"]:
            pdf.build_lists(data["lists"])
            pdf.build_notes(data)
        else:
            pdf.build_empty(data)
        return bytes(pdf.output())


# ── Gantt em planilha (.xlsx) ─────────────────────────────────────────────────
# As barras são células pintadas: uma coluna por dia (ou por semana, em cronogramas
# longos). Fica editável e filtrável no Excel, ao contrário do PDF.

_XLSX_DAILY_LIMIT = 190        # acima disto a coluna passa a valer uma semana
_HEX = {
    "navy": "1B3A6B", "blue_bg": "EFF6FF", "blue_txt": "1E40AF", "gray_50": "F8FAFC", "gray_200": "E2E8F0",
    "gray_400": "94A3B8", "gray_600": "475569", "dark": "0F172A", "white": "FFFFFF",
    "track": "BFDBFE", "progress": "3B82F6", "done": "16A34A", "late_track": "FECACA", "late": "DC2626",
    "summary": "475569", "summary_done": "94A3B8", "rest": "F1F5F9",
}


def render_gantt_xlsx(data: dict) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    lang = data.get("lang", "pt")
    t = get_strings(lang)
    months = _MONTHS[lang]

    def fill(key: str) -> PatternFill:
        return PatternFill("solid", fgColor=_HEX[key])

    wb = Workbook()
    ws = wb.active
    ws.title = (data["folder_name"] or "Gantt").translate({ord(c): "-" for c in "[]:*?/\\"})[:31] or "Gantt"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.outlinePr.summaryBelow = False    # o resumo fica acima das tarefas dele

    labels = [t["col_task"], t["col_start"], t["col_end"], t["col_duration"], "%", t["col_status"]]
    widths = [48, 11.5, 11.5, 9, 7, 15]
    first_col = len(labels) + 1
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    ws.cell(row=1, column=1, value=f"{data['folder_name']} - {t['gantt_title']}").font = Font(bold=True, size=14, color=_HEX["navy"])
    lists = data["lists"]
    if not lists:
        ws.cell(row=3, column=1, value=t["gantt_no_dates"]).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[3].height = 48
        buffer = BytesIO()
        wb.save(buffer)
        return buffer.getvalue()

    ws.cell(row=2, column=1, value=t["gantt_meta"].format(
        start=data["first_day"].strftime("%d/%m/%Y"), end=data["last_day"].strftime("%d/%m/%Y"),
        n=data["total_tasks"], date=data["generated_at"])).font = Font(size=9, color=_HEX["gray_600"])

    start, end, today = data["range_start"], data["range_end"], data["today"]
    total_days = (end - start).days + 1
    daily = total_days <= _XLSX_DAILY_LIMIT
    step = 1 if daily else 7
    units = [start + timedelta(days=i) for i in range(0, total_days, step)]   # início de cada coluna
    rest_days = {i for i, flag in enumerate(settings.schedule_weekend_mask[:7]) if flag == "1"}

    def unit_index(day: date) -> int:
        return (day - start).days // step

    for i in range(len(units)):
        ws.column_dimensions[get_column_letter(first_col + i)].width = 2.9 if daily else 5.2

    # ── cabeçalho: meses, semanas (dd/mm da segunda-feira) e, por dia, o número do dia
    month_row, week_row = 4, 5
    day_row = 6 if daily else None
    header_last = day_row or week_row
    white_bold = Font(bold=True, color=_HEX["white"], size=9)
    center = Alignment(horizontal="center", vertical="center")
    thin_white = Side(style="thin", color=_HEX["white"])
    for index, label in enumerate(labels, start=1):
        ws.merge_cells(start_row=month_row, start_column=index, end_row=header_last, end_column=index)
        cell = ws.cell(row=month_row, column=index, value=label)
        cell.font, cell.fill = white_bold, fill("navy")
        cell.alignment = Alignment(horizontal="left" if index == 1 else "center", vertical="center")
        for r in range(month_row + 1, header_last + 1):
            ws.cell(row=r, column=index).fill = fill("navy")

    def span_header(row: int, first: int, last: int, text: str, fill_key: str, font: Font) -> None:
        if last > first:
            ws.merge_cells(start_row=row, start_column=first_col + first, end_row=row, end_column=first_col + last)
        for i in range(first, last + 1):
            c = ws.cell(row=row, column=first_col + i)
            c.fill = fill(fill_key)
            c.border = Border(left=thin_white if i == first else None)
        cell = ws.cell(row=row, column=first_col + first, value=text)
        cell.font, cell.alignment = font, center

    i = 0
    while i < len(units):
        j = i
        while j + 1 < len(units) and (units[j + 1].year, units[j + 1].month) == (units[i].year, units[i].month):
            j += 1
        wide = (j - i + 1) * (2.9 if daily else 5.2) >= 9
        text = f"{months[units[i].month - 1]}/{units[i].year}" if wide else months[units[i].month - 1]
        span_header(month_row, i, j, text, "navy", white_bold)
        i = j + 1
    week_font = Font(size=8, color=_HEX["blue_txt"], bold=True)
    if daily:
        for i in range(0, len(units), 7):
            span_header(week_row, i, min(i + 6, len(units) - 1), units[i].strftime("%d/%m"), "blue_bg", week_font)
        for i, day in enumerate(units):
            cell = ws.cell(row=day_row, column=first_col + i, value=day.day)
            cell.font = Font(size=7, color=_HEX["gray_600"])
            cell.alignment = center
            cell.fill = fill("rest" if day.weekday() in rest_days else "gray_50")
    else:
        for i, day in enumerate(units):
            span_header(week_row, i, i, day.strftime("%d/%m"), "blue_bg", week_font)

    # ── linhas ────────────────────────────────────────────────────────────────
    date_format = "DD/MM/YYYY"
    today_side = Side(style="medium", color=_HEX["late"])
    today_unit = unit_index(today) if start <= today <= end else None
    row = header_last + 1
    ws.freeze_panes = ws.cell(row=row, column=first_col)

    for lst in lists:
        for col in range(1, first_col + len(units)):
            ws.cell(row=row, column=col).fill = fill("blue_bg")
        ws.cell(row=row, column=1, value=lst["name"].upper()).font = Font(bold=True, color=_HEX["blue_txt"], size=10)
        row += 1
        for item in lst["rows"]:
            level, is_summary = item["level"], item["is_summary"]
            muted = item["is_done"]
            color = _HEX["gray_400"] if muted else _HEX["late"] if item["is_overdue"] else _HEX["dark"]
            font = Font(bold=is_summary, size=9, color=color)
            name = ws.cell(row=row, column=1, value=item["name"])
            name.font, name.alignment = font, Alignment(indent=level * 2, vertical="center")
            for col, value in ((2, item["start"]), (3, item["end"])):
                cell = ws.cell(row=row, column=col, value=value)
                cell.number_format, cell.font, cell.alignment = date_format, font, center
            duration = ws.cell(row=row, column=4, value=item.get("duration_days"))
            duration.font, duration.alignment, duration.number_format = font, center, "0.##"
            pct = item["progress_pct"]
            percent = ws.cell(row=row, column=5, value=None if pct is None else pct / 100)
            percent.number_format, percent.font, percent.alignment = "0%", font, center
            status = ws.cell(row=row, column=6, value=item.get("status") or "")
            status.font, status.alignment = font, center
            ws.row_dimensions[row].outlineLevel = min(level, 7)

            first, last = unit_index(item["start"]), unit_index(item["end"])
            if is_summary:
                keys = ["summary_done" if muted else "summary"] * (last - first + 1)
            else:
                share = 1.0 if item["is_done"] else min(max((pct or 0.0) / 100, 0.0), 1.0)
                filled = round((last - first + 1) * share)
                if 0 < share and filled == 0:
                    filled = 1                      # começou: pelo menos uma célula
                done_key = "done" if item["is_done"] else "late" if item["is_overdue"] else "progress"
                rest_key = "late_track" if item["is_overdue"] else "track"
                keys = [done_key] * filled + [rest_key] * (last - first + 1 - filled)
            for offset, key in enumerate(keys):
                ws.cell(row=row, column=first_col + first + offset).fill = fill(key)
            if daily:
                for i, day in enumerate(units):       # dia de folga fora das barras, só para leitura
                    if day.weekday() in rest_days and not (first <= i <= last):
                        ws.cell(row=row, column=first_col + i).fill = fill("rest")
            row += 1

    last_row = row - 1
    if today_unit is not None:
        for r in range(month_row, last_row + 1):
            cell = ws.cell(row=r, column=first_col + today_unit)
            cell.border = Border(left=today_side, right=today_side)

    # ── legenda e notas ───────────────────────────────────────────────────────
    row += 1
    legend = [
        (t["gantt_legend_planned"], "track"), (t["gantt_legend_progress"], "progress"),
        (t["gantt_legend_done"], "done"), (t["gantt_legend_overdue"], "late"),
        (t["gantt_legend_summary"], "summary"),
    ]
    for label, key in legend:
        ws.cell(row=row, column=2).fill = fill(key)
        ws.cell(row=row, column=1, value=label).font = Font(size=9, color=_HEX["gray_600"])
        row += 1
    ws.cell(row=row, column=1, value=f"{t['gantt_today']}: {today.strftime('%d/%m/%Y')}").font = Font(size=9, color=_HEX["late"], bold=True)
    row += 1
    if data["undated_lists"]:
        ws.cell(row=row, column=1, value=t["gantt_undated_lists"].format(names=", ".join(data["undated_lists"]))).font = Font(size=9, color=_HEX["gray_600"])
        row += 1
    ws.cell(row=row, column=1, value=t["disc_footnote"].format(date=data["generated_at"])).font = Font(size=8, color=_HEX["gray_400"])

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{month_row}:{header_last}"

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
