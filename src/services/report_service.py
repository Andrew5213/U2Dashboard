import asyncio
from datetime import datetime
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from sqlalchemy.ext.asyncio import AsyncSession
from src.repositories.cache_repository import CacheRepository
from src.services.weights_config import compute_province_progress
from src.core.logging import logger

# ── Paleta de cores ──────────────────────────────────────────────────────────
NAVY   = (27,  58, 107)   # #1B3A6B — primária
BLUE   = (59, 130, 246)   # #3b82f6 — acento
GREEN  = (22, 163,  74)   # #16a34a — sucesso
RED    = (220,  38,  38)  # #dc2626 — perigo
AMBER  = (217, 119,   6)  # #d97706 — alerta
WHITE  = (255, 255, 255)
GRAY_50  = (248, 250, 252)  # fundo alternado
GRAY_200 = (226, 232, 240)  # borda leve
GRAY_400 = (148, 163, 184)  # texto auxiliar
GRAY_600 = ( 71,  85, 105)  # texto secundário
DARK     = ( 15,  23,  42)  # texto principal
BLUE_BG  = (239, 246, 255)  # fundo linha de pasta
BLUE_TXT = ( 30,  64, 175)  # texto linha de pasta


_LATIN1_MAP = str.maketrans({
    "—": "-",    # em dash
    "–": "-",    # en dash
    "…": "...",  # ellipsis
    "→": "->",
    "←": "<-",
    "↔": "<->",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "•": "*",    # bullet
    "▸": ">",    # filled right-pointing small triangle
})


def _s(text: str | None) -> str:
    """Sanitiza texto para Latin-1 (exigido pelas fontes internas do fpdf2)."""
    if not text:
        return ""
    return text.translate(_LATIN1_MAP)


def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _pct_color(rate: float) -> tuple:
    if rate >= 0.70:
        return GREEN
    if rate >= 0.40:
        return AMBER
    return RED


class _Report(FPDF):
    """Subclasse FPDF com cabeçalho e rodapé customizados."""

    def __init__(self, space_name: str, generated_at: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.space_name = space_name
        self.generated_at = generated_at
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(left=14, top=16, right=14)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        # Faixa lateral esquerda
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 3, 6, style="F")
        # Data de geração (canto superior direito)
        self.set_font("Helvetica", size=7)
        self.set_text_color(*GRAY_400)
        self.set_xy(14, 5)
        self.cell(0, 4, f"{self.generated_at} (UTC)", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-12)
        self.set_font("Helvetica", size=7)
        self.set_text_color(*GRAY_400)
        self.cell(0, 4, f"U2 Broadcast  -  Relatorio de Projetos  -  Pagina {self.page_no()} de {{nb}}", align="C")

    # ── Helpers de estilo ────────────────────────────────────────────────────

    def _set_text(self, color: tuple) -> None:
        self.set_text_color(*color)

    def _section_header(self, title: str, subtitle: str = "") -> None:
        h = 8 if not subtitle else 12
        x, y = self.get_x(), self.get_y()
        self.set_fill_color(*NAVY)
        self.rect(x, y, 3, h, style="F")
        self.set_fill_color(*GRAY_50)
        self.rect(x + 3, y, 179, h, style="F")
        self.set_xy(x + 6, y + 1.5)
        self.set_font("Helvetica", style="B", size=9)
        self._set_text(NAVY)
        self.cell(0, 5, _s(title.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if subtitle:
            self.set_xy(x + 6, y + 7)
            self.set_font("Helvetica", size=7)
            self._set_text(GRAY_600)
            self.cell(0, 4, _s(subtitle), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def _table_header(self, cols: list[tuple[str, float, str]]) -> None:
        """Cabecalho de tabela. cols = [(label, width_mm, align)]"""
        self.set_fill_color(*NAVY)
        self._set_text(WHITE)
        self.set_font("Helvetica", style="B", size=7)
        for label, w, align in cols:
            self.cell(w, 6, _s(label), border=0, fill=True, align=align,
                      new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln(6)

    def _table_row(self, cells: list[tuple[str, float, str]],
                   fill: bool = False, fill_color: tuple | None = None,
                   text_color: tuple = DARK, bold: bool = False) -> None:
        if fill_color:
            self.set_fill_color(*fill_color)
        elif fill:
            self.set_fill_color(*GRAY_50)
        self.set_font("Helvetica", style="B" if bold else "", size=8)
        self._set_text(text_color)
        for text, w, align in cells:
            self.cell(w, 6, _s(text), border="B", fill=(fill or fill_color is not None),
                      align=align, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln(6)

    def _badge(self, x: float, y: float, text: str,
               bg: tuple, fg: tuple, w: float = 18) -> None:
        self.set_fill_color(*bg)
        self.set_draw_color(*GRAY_200)
        self.rect(x, y + 0.5, w, 4.5, style="FD")
        self.set_xy(x, y + 0.5)
        self.set_font("Helvetica", style="B", size=7)
        self._set_text(fg)
        self.cell(w, 4.5, text, align="C")

    def _progress_bar(self, x: float, y: float, w: float, rate: float) -> None:
        self.set_fill_color(*GRAY_200)
        self.rect(x, y, w, 2.5, style="F")
        if rate > 0:
            color = _pct_color(rate)
            self.set_fill_color(*color)
            self.rect(x, y, w * min(rate, 1.0), 2.5, style="F")

    # ── Capa ─────────────────────────────────────────────────────────────────

    def build_cover(self, data: dict) -> None:
        self.add_page()
        # Fundo navy
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 210, 297, style="F")

        # Eyebrow
        self.set_xy(18, 28)
        self.set_font("Helvetica", style="B", size=7)
        self.set_text_color(147, 197, 253)
        self.cell(0, 5, "U2 BROADCAST", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Acento azul
        self.set_fill_color(*BLUE)
        self.rect(18, 36, 18, 2.5, style="F")

        # Título
        self.set_xy(18, 42)
        self.set_font("Helvetica", style="B", size=24)
        self._set_text(WHITE)
        self.multi_cell(174, 10, "Relatorio de\nGestao de Projetos", align="L")

        # Nome da organização
        self.set_xy(18, 68)
        self.set_font("Helvetica", size=13)
        self.set_text_color(147, 197, 253)
        self.cell(0, 8, _s(data["space_name"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Divisor
        self.set_draw_color(37, 99, 235)
        self.set_line_width(0.3)
        self.line(18, 82, 192, 82)

        # KPI boxes da capa
        kw, kh, gap = 54, 22, 4
        kpis_cover = [
            (str(data["kpis"]["total_tasks"]), "TAREFAS TOTAIS"),
            (data["kpis"]["completion_pct"],   "TAXA DE CONCLUSAO"),
            (str(data["kpis"]["overdue_tasks"]), "EM ATRASO"),
        ]
        for i, (val, lbl) in enumerate(kpis_cover):
            kx = 18 + i * (kw + gap)
            ky = 88
            self.set_fill_color(40, 70, 115)
            self.set_draw_color(70, 100, 160)
            self.set_line_width(0.3)
            self.rect(kx, ky, kw, kh, style="FD")
            self.set_xy(kx, ky + 3)
            self.set_font("Helvetica", style="B", size=16)
            self._set_text(WHITE)
            self.cell(kw, 8, val, align="C", new_x=XPos.LEFT, new_y=YPos.NEXT)
            self.set_xy(kx, ky + 13)
            self.set_font("Helvetica", size=6)
            self.set_text_color(147, 197, 253)
            self.cell(kw, 4, lbl, align="C")

        # Metadados
        meta = [
            ("DATA DE GERACAO",             data["generated_at"] + " (UTC)"),
            ("ULTIMA ATUALIZACAO DOS DADOS", data["last_refresh_at"]),
            (f"PASTAS: {data['kpis']['total_folders']}   ·   LISTAS: {data['kpis']['total_lists']}", ""),
        ]
        y0 = 120
        for label, value in meta:
            self.set_xy(18, y0)
            self.set_font("Helvetica", size=7)
            self.set_text_color(191, 219, 254)
            self.cell(0, 4, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if value:
                self.set_xy(18, y0 + 5)
                self.set_font("Helvetica", style="B", size=9)
                self._set_text(WHITE)
                self.cell(0, 5, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                y0 += 14
            else:
                y0 += 8

        # Nota de rodapé da capa
        self.set_draw_color(255, 255, 255)
        self.set_line_width(0.1)
        self.line(18, 265, 192, 265)
        self.set_xy(18, 268)
        self.set_font("Helvetica", size=7)
        self.set_text_color(96, 165, 250)
        self.multi_cell(174, 4,
            "Documento gerado automaticamente pelo sistema de gestao de projetos U2 Broadcast.\n"
            "Os dados refletem o estado do cache local conforme a ultima sincronizacao indicada acima.",
            align="L"
        )

    # ── Resumo Executivo ─────────────────────────────────────────────────────

    def build_executive_summary(self, data: dict) -> None:
        self.add_page()
        self._section_header("Resumo Executivo",
                              f"Visao consolidada de todos os projetos e tarefas - {_s(data['space_name'])}")

        kpis = data["kpis"]
        cards = [
            ("Total de Tarefas",  str(kpis["total_tasks"]),      DARK,  NAVY,
             f"{kpis['total_folders']} pastas · {kpis['total_lists']} listas"),
            ("Concluidas",        str(kpis["completed_tasks"]),   GREEN, GREEN,
             f"{kpis['completion_pct']} do total"),
            ("Em Atraso",         str(kpis["overdue_tasks"]),
             RED if kpis["overdue_tasks"] > 0 else GREEN,
             RED if kpis["overdue_tasks"] > 0 else GREEN,
             "tarefas vencidas"),
            ("Sem Prazo",         str(kpis["tasks_without_due_date"]), AMBER, AMBER,
             "sem data definida"),
        ]
        cw, ch = 43, 24
        gap = 2.5
        x0 = self.get_x()
        y0 = self.get_y()
        for i, (label, value, val_color, accent, sub) in enumerate(cards):
            cx = x0 + i * (cw + gap)
            cy = y0
            self.set_fill_color(*WHITE)
            self.set_draw_color(*GRAY_200)
            self.set_line_width(0.3)
            self.rect(cx, cy, cw, ch, style="FD")
            # Acento superior
            self.set_fill_color(*accent)
            self.rect(cx, cy, cw, 2, style="F")
            # Valor
            self.set_xy(cx, cy + 4)
            self.set_font("Helvetica", style="B", size=18)
            self._set_text(val_color)
            self.cell(cw, 8, value, align="C", new_x=XPos.LEFT, new_y=YPos.NEXT)
            # Label
            self.set_xy(cx, cy + 13)
            self.set_font("Helvetica", style="B", size=6)
            self._set_text(GRAY_600)
            self.cell(cw, 4, label.upper(), align="C", new_x=XPos.LEFT, new_y=YPos.NEXT)
            # Sub
            self.set_xy(cx, cy + 18)
            self.set_font("Helvetica", size=6)
            self._set_text(GRAY_400)
            self.cell(cw, 4, sub, align="C")

        self.set_y(y0 + ch + 6)

        # Distribuição por status
        dist = kpis.get("status_distribution", {})
        if dist:
            self.set_fill_color(*GRAY_50)
            self.set_draw_color(*GRAY_200)
            box_y = self.get_y()
            self.rect(14, box_y, 182, 5 + len(dist) * 0 + 10, style="FD")
            self.set_xy(18, box_y + 2)
            self.set_font("Helvetica", style="B", size=7)
            self._set_text(GRAY_600)
            self.cell(0, 4, "DISTRIBUICAO POR STATUS", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            col_w = 182 / max(len(dist), 1)
            start_x = 14
            for idx, (status, count) in enumerate(dist.items()):
                self.set_xy(start_x + idx * col_w, box_y + 7)
                self.set_font("Helvetica", style="B", size=9)
                self._set_text(DARK)
                self.cell(col_w, 5, str(count), align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
                self.set_xy(start_x + idx * col_w, box_y + 13)
                self.set_font("Helvetica", size=6)
                self._set_text(GRAY_600)
                self.cell(col_w, 4, status, align="C")
            self.ln(26)

        # ── Top Áreas por Atividade ──────────────────────────────────────────
        folders_data = data.get("folders", [])
        top_folders = sorted(folders_data, key=lambda f: f["total_tasks"], reverse=True)[:8]
        if top_folders:
            self.ln(2)
            self._section_header("Top Areas por Atividade",
                                 "Pastas ordenadas por volume de tarefas e suas taxas de conclusao")
            name_w, bar_w, pct_w, tasks_w = 58, 78, 20, 16
            row_h = 11
            for i, folder in enumerate(top_folders):
                row_y = self.get_y()
                if i % 2 == 0:
                    self.set_fill_color(*GRAY_50)
                    self.rect(14, row_y, 182, row_h, style="F")
                # Nome da pasta
                self.set_xy(16, row_y + 3)
                self.set_font("Helvetica", style="B", size=8)
                self._set_text(DARK)
                self.cell(name_w, 5, _s(folder["name"])[:28])
                # Barra horizontal de progresso
                bar_x = 16 + name_w + 4
                self._progress_bar(bar_x, row_y + 4.5, bar_w, folder["completion_rate"])
                # Percentual
                pct_x = bar_x + bar_w + 4
                self.set_xy(pct_x, row_y + 2.5)
                self.set_font("Helvetica", style="B", size=8)
                self._set_text(_pct_color(folder["completion_rate"]))
                self.cell(pct_w, 6, folder["completion_pct"], align="R")
                # Contagem de tarefas
                tasks_x = pct_x + pct_w + 2
                self.set_xy(tasks_x, row_y + 2.5)
                self.set_font("Helvetica", size=7)
                self._set_text(GRAY_400)
                self.cell(tasks_w, 6, f"{folder['total_tasks']} tar.", align="R")
                self.set_y(row_y + row_h)

        # ── Alertas Executivos ───────────────────────────────────────────────
        self.ln(5)
        self._section_header("Alertas Executivos",
                             "Pontos de atencao identificados automaticamente a partir dos dados")
        alerts: list[tuple[tuple, str]] = []
        total_tasks = kpis["total_tasks"]

        if kpis["overdue_tasks"] > 0:
            alerts.append((RED,
                f"{kpis['overdue_tasks']} tarefa(s) com prazo vencido ainda em aberto - requer atencao imediata."))

        no_due_pct = kpis["tasks_without_due_date"] / total_tasks * 100 if total_tasks > 0 else 0
        if no_due_pct > 50:
            alerts.append((AMBER,
                f"{kpis['tasks_without_due_date']} tarefas ({no_due_pct:.0f}%) sem prazo definido dificultam o planejamento."))

        if kpis["completion_rate"] < 0.10:
            alerts.append((RED,
                f"Taxa de conclusao de {kpis['completion_pct']} indica baixo progresso geral nos projetos."))
        elif kpis["completion_rate"] < 0.40:
            alerts.append((AMBER,
                f"Taxa de conclusao de {kpis['completion_pct']} esta abaixo do ideal (40%)."))
        else:
            alerts.append((GREEN,
                f"Taxa de conclusao de {kpis['completion_pct']} esta dentro do esperado."))

        if top_folders:
            top_ov = max(top_folders, key=lambda f: f.get("overdue_tasks", 0))
            if top_ov.get("overdue_tasks", 0) > 0:
                alerts.append((AMBER,
                    f"Area '{_s(top_ov['name'])}' concentra o maior numero de atrasos ({top_ov['overdue_tasks']} tarefa(s))."))

        if not alerts:
            alerts.append((GREEN, "Nenhum ponto critico identificado nos dados atuais."))

        for color, msg in alerts[:5]:
            row_y = self.get_y()
            self.set_fill_color(*color)
            self.rect(16, row_y + 3, 2.5, 2.5, style="F")
            self.set_xy(21, row_y + 1.5)
            self.set_font("Helvetica", size=8)
            self._set_text(DARK)
            self.multi_cell(171, 5, _s(msg), align="L")
            self.ln(1)

    # ── Saúde dos Projetos ───────────────────────────────────────────────────

    def build_project_health(self, data: dict) -> None:
        self.add_page()
        self._section_header("Saude dos Projetos por Area",
                              "Metricas de conclusao e tarefas em atraso agrupadas por pasta e lista")

        cols = [
            ("Projeto / Lista",    80, "L"),
            ("Tarefas",            20, "C"),
            ("Concluidas",         22, "C"),
            ("Em Atraso",          22, "C"),
            ("Taxa de Conclusao",  38, "C"),
        ]
        self._table_header(cols)

        row_idx = 0
        folders = data.get("folders", [])
        folderless = data.get("folderless_lists", [])

        for folder in folders:
            rate = folder["completion_rate"]
            pct_txt = folder["completion_pct"]
            overdue = folder["overdue_tasks"]
            even = (row_idx % 2 == 0)

            base_y = self.get_y()
            if base_y > 255:
                self.add_page()
                self._table_header(cols)
                base_y = self.get_y()

            self._table_row([
                (_s(folder["name"]),   80, "L"),
                (str(folder["total_tasks"]),      20, "C"),
                (str(folder["completed_tasks"]),  22, "C"),
                ("",                              22, "C"),
                ("",                              38, "C"),
            ], fill_color=BLUE_BG, text_color=BLUE_TXT, bold=True)

            # Badge em atraso na coluna 3
            if overdue > 0:
                badge_x = 14 + 80 + 20 + 22 + 1
                self._badge(badge_x, base_y + 0.5, f"{overdue}", (254, 242, 242), RED, w=18)
            # Barra de progresso na col 4
            bar_x = 14 + 80 + 20 + 22 + 22 + 2
            bar_y = base_y + 1.5
            self._progress_bar(bar_x, bar_y, 32, rate)
            # % texto
            self.set_xy(bar_x, base_y + 0.5)
            self.set_font("Helvetica", style="B", size=7)
            self._set_text(_pct_color(rate))
            self.cell(34, 4.5, pct_txt, align="C")
            # Restaura cursor após overlays para próxima linha ficar no lugar correto
            self.set_y(base_y + 6)

            row_idx += 1

            for lst in folder.get("lists", []):
                l_rate    = lst["completion_rate"]
                l_pct     = lst["completion_pct"]
                l_overdue = lst["overdue_tasks"]
                l_even    = (row_idx % 2 == 0)
                l_y = self.get_y()

                if l_y > 255:
                    self.add_page()
                    self._table_header(cols)
                    l_y = self.get_y()

                self._table_row([
                    (f"  . {_s(lst['name'])}",       80, "L"),
                    (str(lst["total_tasks"]),        20, "C"),
                    (str(lst["completed_tasks"]),    22, "C"),
                    ("",                             22, "C"),
                    ("",                             38, "C"),
                ], fill=l_even, text_color=GRAY_600)

                if l_overdue > 0:
                    badge_x = 14 + 80 + 20 + 22 + 1
                    self._badge(badge_x, l_y + 0.5, f"{l_overdue}", (254, 242, 242), RED, w=18)
                self.set_xy(14 + 80 + 20 + 22 + 22 + 2, l_y + 0.5)
                self.set_font("Helvetica", size=7)
                self._set_text(_pct_color(l_rate))
                self.cell(34, 4.5, l_pct, align="C")
                self.set_y(l_y + 6)
                row_idx += 1

        for lst in folderless:
            l_rate    = lst["completion_rate"]
            l_pct     = lst["completion_pct"]
            l_overdue = lst["overdue_tasks"]
            l_even    = (row_idx % 2 == 0)
            l_y = self.get_y()

            if l_y > 255:
                self.add_page()
                self._table_header(cols)
                l_y = self.get_y()

            self._table_row([
                (_s(lst["name"]),                80, "L"),
                (str(lst["total_tasks"]),         20, "C"),
                (str(lst["completed_tasks"]),     22, "C"),
                ("",                              22, "C"),
                ("",                              38, "C"),
            ], fill=l_even, text_color=DARK)

            if l_overdue > 0:
                badge_x = 14 + 80 + 20 + 22 + 1
                self._badge(badge_x, l_y + 0.5, f"{l_overdue}", (254, 242, 242), RED, w=18)
            self.set_xy(14 + 80 + 20 + 22 + 22 + 2, l_y + 0.5)
            self.set_font("Helvetica", size=7)
            self._set_text(_pct_color(l_rate))
            self.cell(34, 4.5, l_pct, align="C")
            self.set_y(l_y + 6)
            row_idx += 1

        if not folders and not folderless:
            self.set_font("Helvetica", "I", size=8)
            self._set_text(GRAY_400)
            self.cell(182, 10, "Nenhum projeto encontrado. Execute uma atualizacao de cache.", align="C",
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ── Tarefas em Atraso ────────────────────────────────────────────────────

    def build_overdue(self, tasks: list[dict]) -> None:
        if not tasks:
            return
        self.add_page()
        self._section_header(f"Tarefas em Atraso ({len(tasks)})",
                              "Tarefas com prazo vencido ainda pendentes de conclusao, por data de vencimento")

        cols = [
            ("Tarefa",          60, "L"),
            ("Lista / Projeto", 28, "L"),
            ("Responsavel",     55, "L"),
            ("Vencimento",      22, "C"),
            ("Atraso",          17, "C"),
        ]
        self._table_header(cols)

        for i, task in enumerate(tasks):
            even = (i % 2 == 0)
            days = task["days_overdue"]
            row_y = self.get_y()
            if row_y > 255:
                self.add_page()
                self._table_header(cols)
                row_y = self.get_y()

            self._table_row([
                (_s(task["name"])[:50] + ("..." if len(task["name"]) > 50 else ""), 60, "L"),
                (task["list_name"][:18], 28, "L"),
                (task["assignees_str"][:30], 55, "L"),
                (task["due_date_fmt"],  22, "C"),
                ("",                    17, "C"),
            ], fill=even, text_color=DARK)

            badge_txt = f"{days} dia{'s' if days != 1 else ''}"
            self._badge(14 + 60 + 28 + 55 + 22 + 1, row_y + 0.5, badge_txt,
                        (254, 242, 242), RED, w=15)
            self.set_y(row_y + 6)

    # ── Próximas Entregas ────────────────────────────────────────────────────

    def build_upcoming(self, tasks: list[dict]) -> None:
        if not tasks:
            return
        self.add_page()
        self._section_header(f"Proximas Entregas - 30 dias ({len(tasks)})",
                              "Tarefas abertas com vencimento nos proximos 30 dias, em ordem cronologica")

        cols = [
            ("Tarefa",          62, "L"),
            ("Lista / Projeto", 28, "L"),
            ("Responsavel",     55, "L"),
            ("Vencimento",      22, "C"),
            ("Area",            15, "L"),
        ]
        self._table_header(cols)

        for i, task in enumerate(tasks):
            even = (i % 2 == 0)
            row_y = self.get_y()
            if row_y > 255:
                self.add_page()
                self._table_header(cols)

            self._table_row([
                (_s(task["name"])[:52] + ("..." if len(task["name"]) > 52 else ""), 62, "L"),
                ((task.get("list_name") or "N/D")[:18], 28, "L"),
                (task["assignees_str"][:30],            55, "L"),
                (task["due_date_fmt"],                  22, "C"),
                ((task.get("folder_name") or "N/D")[:14], 15, "L"),
            ], fill=even, text_color=DARK)

    # ── Desempenho da Equipe ─────────────────────────────────────────────────

    def build_team(self, stats: list[dict]) -> None:
        if not stats:
            return
        self.add_page()
        self._section_header("Desempenho da Equipe",
                              "Tarefas em aberto, concluidas e em atraso por responsavel")

        cols = [
            ("Responsavel",        60, "L"),
            ("Em Aberto",          28, "C"),
            ("Concluidas",         28, "C"),
            ("Em Atraso",          28, "C"),
            ("Taxa de Conclusao",  38, "C"),
        ]
        self._table_header(cols)

        for i, person in enumerate(stats):
            even = (i % 2 == 0)
            row_y = self.get_y()
            if row_y > 255:
                self.add_page()
                self._table_header(cols)
                row_y = self.get_y()

            color = _pct_color(person["completion_rate"]) if person["total"] > 0 else GRAY_400

            self._table_row([
                (person["assignee"][:35],         60, "L"),
                (str(person["open"]),              28, "C"),
                (str(person["completed"]),         28, "C"),
                ("",                               28, "C"),
                (person["completion_pct"],         38, "C"),
            ], fill=even, text_color=DARK, bold=(i == 0))

            # Taxa colorida
            pct_x = 14 + 60 + 28 + 28 + 28
            self.set_xy(pct_x, row_y + 0.5)
            self.set_font("Helvetica", style="B", size=8)
            self._set_text(color)
            self.cell(38, 5, person["completion_pct"], align="C")

            if person["overdue"] > 0:
                badge_x = 14 + 60 + 28 + 28 + 1
                self._badge(badge_x, row_y + 0.5, str(person["overdue"]),
                            (254, 242, 242), RED, w=22)
            self.set_y(row_y + 6)

    # ── Capa Província ───────────────────────────────────────────────────────

    def build_cover_provincia(self, data: dict) -> None:
        self.add_page()
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 210, 297, style="F")

        self.set_xy(18, 28)
        self.set_font("Helvetica", style="B", size=7)
        self.set_text_color(147, 197, 253)
        self.cell(0, 5, "U2 BROADCAST  ·  RELATORIO DE PROVINCIA", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_fill_color(*BLUE)
        self.rect(18, 36, 18, 2.5, style="F")

        self.set_xy(18, 42)
        self.set_font("Helvetica", style="B", size=22)
        self._set_text(WHITE)
        self.multi_cell(174, 9, f"Relatorio Detalhado\nde Provincia", align="L")

        self.set_xy(18, 66)
        self.set_font("Helvetica", style="B", size=16)
        self.set_text_color(147, 197, 253)
        self.cell(0, 8, _s(data["folder_name"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_xy(18, 76)
        self.set_font("Helvetica", size=9)
        self.set_text_color(191, 219, 254)
        self.cell(0, 5, _s(data["space_name"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_draw_color(37, 99, 235)
        self.set_line_width(0.3)
        self.line(18, 87, 192, 87)

        kpis = data["kpis"]
        weighted_progress = data.get("weighted_progress")
        weights_configured = data.get("weights_configured", False)
        wp_pct = data.get("weighted_progress_pct", "—")

        # Se pesos configurados: 4 KPIs na capa; senão 3
        if weights_configured and weighted_progress is not None:
            kw, kh, gap = 40, 22, 3
            kpis_cover = [
                (str(kpis["total_tasks"]),     "TAREFAS TOTAIS"),
                (kpis["completion_pct"],       "TAXA SIMPLES"),
                (wp_pct,                       "PROG. PONDERADO"),
                (str(kpis["overdue_tasks"]),   "EM ATRASO"),
            ]
        else:
            kw, kh, gap = 54, 22, 4
            kpis_cover = [
                (str(kpis["total_tasks"]),     "TAREFAS TOTAIS"),
                (kpis["completion_pct"],       "TAXA DE CONCLUSAO"),
                (str(kpis["overdue_tasks"]),   "EM ATRASO"),
            ]
        for i, (val, lbl) in enumerate(kpis_cover):
            kx = 18 + i * (kw + gap)
            ky = 94
            self.set_fill_color(40, 70, 115)
            self.set_draw_color(70, 100, 160)
            self.set_line_width(0.3)
            self.rect(kx, ky, kw, kh, style="FD")
            self.set_xy(kx, ky + 3)
            self.set_font("Helvetica", style="B", size=14)
            self._set_text(WHITE)
            self.cell(kw, 8, val, align="C", new_x=XPos.LEFT, new_y=YPos.NEXT)
            self.set_xy(kx, ky + 13)
            self.set_font("Helvetica", size=6)
            self.set_text_color(147, 197, 253)
            self.cell(kw, 4, lbl, align="C")

        y0 = 126
        meta = [
            ("LISTAS", str(data["total_lists"])),
            ("DATA DE GERACAO", data["generated_at"] + " (UTC)"),
            ("ULTIMA ATUALIZACAO", data["last_refresh_at"]),
        ]
        for label, value in meta:
            self.set_xy(18, y0)
            self.set_font("Helvetica", size=7)
            self.set_text_color(191, 219, 254)
            self.cell(0, 4, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_xy(18, y0 + 5)
            self.set_font("Helvetica", style="B", size=9)
            self._set_text(WHITE)
            self.cell(0, 5, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            y0 += 14

        self.set_draw_color(255, 255, 255)
        self.set_line_width(0.1)
        self.line(18, 265, 192, 265)
        self.set_xy(18, 268)
        self.set_font("Helvetica", size=7)
        self.set_text_color(96, 165, 250)
        self.multi_cell(174, 4,
            "Documento gerado automaticamente pelo sistema de gestao de projetos U2 Broadcast.\n"
            "Os dados refletem o estado do cache local conforme a ultima sincronizacao indicada acima.",
        )

    # ── Resumo Província ─────────────────────────────────────────────────────

    def build_resumo_provincia(self, data: dict) -> None:
        self.add_page()
        self._section_header(f"Resumo - {_s(data['folder_name'])}",
                              f"Visao consolidada das listas e tarefas da provincia - {_s(data['space_name'])}")

        kpis = data["kpis"]
        cards = [
            ("Total de Tarefas", str(kpis["total_tasks"]), DARK, NAVY,
             f"{data['total_lists']} lista(s)"),
            ("Concluidas",       str(kpis["completed_tasks"]), GREEN, GREEN,
             f"{kpis['completion_pct']} do total"),
            ("Em Atraso",        str(kpis["overdue_tasks"]),
             RED if kpis["overdue_tasks"] > 0 else GREEN,
             RED if kpis["overdue_tasks"] > 0 else GREEN,
             "tarefas vencidas"),
            ("Sem Prazo",        str(kpis["tasks_without_due_date"]), AMBER, AMBER,
             "sem data definida"),
        ]
        cw, ch = 43, 24
        gap = 2.5
        x0, y0 = self.get_x(), self.get_y()
        for i, (label, value, val_color, accent, sub) in enumerate(cards):
            cx = x0 + i * (cw + gap)
            self.set_fill_color(*WHITE)
            self.set_draw_color(*GRAY_200)
            self.set_line_width(0.3)
            self.rect(cx, y0, cw, ch, style="FD")
            self.set_fill_color(*accent)
            self.rect(cx, y0, cw, 2, style="F")
            self.set_xy(cx, y0 + 4)
            self.set_font("Helvetica", style="B", size=18)
            self._set_text(val_color)
            self.cell(cw, 8, value, align="C")
            self.set_xy(cx, y0 + 13)
            self.set_font("Helvetica", style="B", size=6)
            self._set_text(GRAY_600)
            self.cell(cw, 4, label.upper(), align="C")
            self.set_xy(cx, y0 + 18)
            self.set_font("Helvetica", size=6)
            self._set_text(GRAY_400)
            self.cell(cw, 4, sub, align="C")
        self.set_y(y0 + ch + 6)

        # Distribuição por status
        dist = kpis.get("status_distribution", {})
        if dist:
            box_y = self.get_y()
            self.set_fill_color(*GRAY_50)
            self.set_draw_color(*GRAY_200)
            self.rect(14, box_y, 182, 20, style="FD")
            self.set_xy(18, box_y + 2)
            self.set_font("Helvetica", style="B", size=7)
            self._set_text(GRAY_600)
            self.cell(0, 4, "DISTRIBUICAO POR STATUS", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            col_w = 182 / max(len(dist), 1)
            for idx, (status, count) in enumerate(dist.items()):
                self.set_xy(14 + idx * col_w, box_y + 7)
                self.set_font("Helvetica", style="B", size=9)
                self._set_text(DARK)
                self.cell(col_w, 5, str(count), align="C")
                self.set_xy(14 + idx * col_w, box_y + 13)
                self.set_font("Helvetica", size=6)
                self._set_text(GRAY_600)
                self.cell(col_w, 4, _s(status), align="C")
            self.set_y(box_y + 26)

        # Progresso Ponderado por Disciplina (se configurado)
        weighted_progress = data.get("weighted_progress")
        disciplines = data.get("disciplines", [])
        weights_configured = data.get("weights_configured", False)

        if weights_configured and weighted_progress is not None:
            self.ln(4)
            self._section_header(
                "Progresso Ponderado por Disciplina",
                "Avanço fisico calculado pelo peso de cada disciplina (EVM - Earned Value Method)",
            )
            # Barra de progresso geral ponderado
            wp_pct = data.get("weighted_progress_pct", _pct(weighted_progress))
            bar_y = self.get_y()
            self.set_fill_color(*GRAY_50)
            self.set_draw_color(*GRAY_200)
            self.rect(14, bar_y, 182, 14, style="FD")
            self.set_xy(18, bar_y + 2)
            self.set_font("Helvetica", style="B", size=7)
            self._set_text(GRAY_600)
            self.cell(0, 4, "PROGRESSO FISICO GLOBAL PONDERADO", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self._progress_bar(18, bar_y + 7, 140, weighted_progress)
            self.set_xy(160, bar_y + 5.5)
            self.set_font("Helvetica", style="B", size=11)
            self._set_text(_pct_color(weighted_progress))
            self.cell(34, 6, wp_pct, align="C")
            self.set_y(bar_y + 18)

            # Tabela de disciplinas com pesos e contribuição
            d_cols = [
                ("Disciplina",     72, "L"),
                ("Peso",           20, "C"),
                ("Progresso",      30, "C"),
                ("Contribuicao",   28, "C"),
                ("Tarefas",        16, "C"),
                ("Taxa",           16, "C"),
            ]
            self._table_header(d_cols)
            for i, disc in enumerate(disciplines):
                row_y = self.get_y()
                even = (i % 2 == 0)
                w_txt = f"{round((disc['weight'] or 0) * 100, 1):.1f}%" if disc["weight"] is not None else "—"
                contrib_txt = f"{round((disc['weighted_contribution'] or 0) * 100, 1):.1f}%" if disc.get("weighted_contribution") is not None else "—"
                self._table_row([
                    (_s(disc["name"])[:30],             72, "L"),
                    (w_txt,                             20, "C"),
                    ("",                                30, "C"),
                    (contrib_txt,                       28, "C"),
                    (str(disc["total_tasks"]),          16, "C"),
                    ("",                                16, "C"),
                ], fill=even, text_color=DARK)
                # Barra de progresso inline
                self._progress_bar(14 + 72 + 20 + 2, row_y + 1.5, 24, disc["completion_rate"])
                self.set_xy(14 + 72 + 20 + 2, row_y + 0.5)
                self.set_font("Helvetica", style="B", size=6)
                self._set_text(_pct_color(disc["completion_rate"]))
                self.cell(28, 4.5, disc["completion_pct"] if "completion_pct" in disc else _pct(disc["completion_rate"]), align="C")
                # Taxa de conclusão — coluna Taxa (72+20+30+28+16=166 de margem → inicia em 14+166=180)
                rate_x = 14 + 72 + 20 + 30 + 28 + 16
                self.set_xy(rate_x, row_y + 0.5)
                self.set_font("Helvetica", style="B", size=7)
                self._set_text(_pct_color(disc["completion_rate"]))
                self.cell(16, 4.5, _pct(disc["completion_rate"]), align="C")
                self.set_y(row_y + 6)

        # Tabela resumo de listas
        self.ln(4)
        uses_weight = weights_configured
        list_cols = [
            ("Lista",            66 if uses_weight else 80, "L"),
            ("Tarefas",          24, "C"),
            ("Concluidas",       24, "C"),
            ("Em Atraso",        24, "C"),
        ]
        if uses_weight:
            list_cols.append(("Peso",    14, "C"))
            list_cols.append(("Taxa",    30, "C"))
        else:
            list_cols.append(("Taxa Conclusao", 44, "C"))
        self._section_header("Resumo por Lista / Disciplina", "Metricas de conclusao e atrasos por disciplina desta provincia")
        self._table_header(list_cols)
        name_w = 66 if uses_weight else 80
        for i, lst in enumerate(data["lists"]):
            row_y = self.get_y()
            if row_y > 262:
                self.add_page()
                self._section_header("Resumo por Lista / Disciplina (cont.)")
                self._table_header(list_cols)
                row_y = self.get_y()
            even = (i % 2 == 0)
            w_txt = lst.get("weight_pct") or "—"
            row_cells = [
                (_s(lst["name"]),            name_w, "L"),
                (str(lst["total_tasks"]),     24,    "C"),
                (str(lst["completed_tasks"]), 24,    "C"),
                ("",                          24,    "C"),
            ]
            if uses_weight:
                row_cells.append((w_txt, 14, "C"))
                row_cells.append(("",    30, "C"))
            else:
                row_cells.append(("",    44, "C"))
            self._table_row(row_cells, fill=even, text_color=DARK)
            if lst["overdue_tasks"] > 0:
                ov_x = 14 + name_w + 24 + 24 + 2
                self._badge(ov_x, row_y + 0.5, str(lst["overdue_tasks"]),
                            (254, 242, 242), RED, w=18)
            bar_x = 14 + name_w + 24 + 24 + 24 + (14 if uses_weight else 0) + 2
            bar_w = 24
            self._progress_bar(bar_x, row_y + 1.5, bar_w, lst["completion_rate"])
            self.set_xy(bar_x, row_y + 0.5)
            self.set_font("Helvetica", style="B", size=7)
            self._set_text(_pct_color(lst["completion_rate"]))
            self.cell(bar_w + 4, 4.5, lst["completion_pct"], align="C")
            self.set_y(row_y + 6)

    # ── Bloco compacto de pesos por disciplina ────────────────────────────────

    def _build_discipline_weights_block(self, task_details: list[dict]) -> None:
        if not task_details:
            return
        row_h = 4.5
        title_h = 5.0   # título do bloco
        hdr_h  = 4.0    # cabeçalho das colunas
        block_h = title_h + hdr_h + len(task_details) * row_h + 2.0
        block_y = self.get_y()

        self.set_fill_color(*BLUE_BG)
        self.set_draw_color(*GRAY_200)
        self.set_line_width(0.2)
        self.rect(14, block_y, 182, block_h, style="FD")

        # ── Título ────────────────────────────────────────────────────────────
        self.set_xy(16, block_y + 1.2)
        self.set_font("Helvetica", style="B", size=6)
        self._set_text(BLUE_TXT)
        self.cell(0, 3.5, "PESOS POR DISCIPLINA  (progresso ponderado por engenharia)",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # ── Cabeçalho das colunas ─────────────────────────────────────────────
        # Layout: Nome(82) | barra_peso(36) | Peso%(16) | Avanco%(16) | Contrib%(16)
        hdr_y = block_y + title_h
        bar_x = 14 + 82 + 2
        self.set_xy(16, hdr_y)
        self.set_font("Helvetica", style="B", size=5)
        self._set_text(GRAY_600)
        self.cell(82, hdr_h, "DISCIPLINA", align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_xy(bar_x, hdr_y)
        self.cell(36, hdr_h, "PESO REL.", align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.cell(16, hdr_h, "PESO %", align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.cell(16, hdr_h, "AVANCO %", align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.cell(16, hdr_h, "CONTRIB.", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # Linha separadora fina
        sep_y = hdr_y + hdr_h - 0.5
        self.set_draw_color(*GRAY_200)
        self.line(16, sep_y, 194, sep_y)

        # ── Linhas por disciplina ─────────────────────────────────────────────
        # Colunas: Nome(82) | barra_peso(36) | Peso%(16) | Avanco%(16) | Contrib%(16)
        for td in task_details:
            row_y = self.get_y()
            name_txt = _s(td["name"])
            name_txt = name_txt[:40] + "..." if len(name_txt) > 40 else name_txt
            w_norm = td.get("weight_norm", 0.0)
            prog   = td.get("progress", 0.0)
            # Contribuição = fração do peso × progresso = quanto esta disciplina
            # adiciona ao progresso total ponderado da lista
            contrib = w_norm * prog

            # Nome da disciplina
            self.set_xy(16, row_y + 0.5)
            self.set_font("Helvetica", size=6)
            self._set_text(GRAY_400 if td.get("is_done") else DARK)
            self.cell(82, row_h - 1, name_txt, align="L")

            # Barra de peso relativo (100% = disciplina com maior peso da lista)
            bar_x = 14 + 82 + 2
            self._progress_bar(bar_x, row_y + 1.8, 34, w_norm)

            # Peso % — participação desta disciplina no total da lista
            self.set_xy(bar_x + 36, row_y + 0.5)
            self.set_font("Helvetica", style="B", size=6)
            self._set_text(BLUE_TXT)
            self.cell(16, row_h - 1, f"{w_norm*100:.1f}%", align="C")

            # Avanço % — quanto desta disciplina já foi concluído
            self.set_font("Helvetica", style="B", size=6)
            self._set_text(_pct_color(prog))
            self.cell(16, row_h - 1, f"{prog*100:.1f}%", align="C")

            # Contribuição ao progresso ponderado da lista (Peso% × Avanço%)
            self.set_font("Helvetica", size=6)
            self._set_text(GRAY_600)
            self.cell(16, row_h - 1, f"+{contrib*100:.1f}%", align="C")

            self.set_y(row_y + row_h)

        self.ln(3)

    # ── Detalhamento por Lista ────────────────────────────────────────────────

    def build_listas_detail(self, lists_detail: list[dict]) -> None:
        cols = [
            ("Tarefa",       65, "L"),
            ("Peso",         10, "C"),
            ("Status",       33, "L"),
            ("Responsavel",  46, "L"),
            ("Vencimento",   28, "C"),
        ]
        for lst in lists_detail:
            self.add_page()
            self._section_header(
                f"Lista: {_s(lst['name'])}",
                f"{lst['total_tasks']} tarefa(s) · {lst['completed_tasks']} concluida(s) · "
                f"{lst['overdue_tasks']} em atraso · Prog. Pond.: {lst['completion_pct']}",
            )
            # Bloco de pesos das disciplinas (tarefas pai)
            self._build_discipline_weights_block(lst.get("task_details", []))

            tasks = lst.get("tasks", [])
            if not tasks:
                self.set_font("Helvetica", "I", size=8)
                self._set_text(GRAY_400)
                self.cell(182, 10, "Nenhuma tarefa encontrada nesta lista.", align="C",
                          new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                continue

            self._table_header(cols)
            for i, task in enumerate(tasks):
                row_y = self.get_y()
                if row_y > 255:
                    self.add_page()
                    self._section_header(f"Lista: {_s(lst['name'])} (cont.)")
                    self._table_header(cols)
                    row_y = self.get_y()

                is_subtask = bool(task.get("parent_task_id"))
                is_done = task["status_type"] in ("done", "closed")
                is_overdue = task.get("is_overdue", False)
                even = (i % 2 == 0)

                asgn = task["assignees_str"]
                asgn = asgn[:30] + "..." if len(asgn) > 30 else asgn

                if is_subtask:
                    row_h = 5
                    if even:
                        self.set_fill_color(248, 248, 252)
                        self.rect(14, row_y, 182, row_h, style="F")
                    # Linha vertical de indentação (azul claro)
                    self.set_fill_color(180, 185, 210)
                    self.rect(20, row_y + 0.8, 0.8, 3.2, style="F")
                    txt_color = GRAY_400 if is_done else (RED if is_overdue else GRAY_600)
                    name_txt = _s(task["name"])
                    name_txt = name_txt[:44] + "..." if len(name_txt) > 44 else name_txt
                    self.set_font("Helvetica", size=7)
                    self._set_text(txt_color)
                    self.set_xy(23, row_y + 0.8)
                    self.cell(56, 4, name_txt, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
                    self.cell(10, 4, "", align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
                    self.cell(33, 4, _s(task["status"] or "-")[:18], align="L",
                              new_x=XPos.RIGHT, new_y=YPos.TOP)
                    self.cell(46, 4, asgn, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
                    self.cell(28, 4, task["due_date_fmt"], align="C",
                              new_x=XPos.LMARGIN, new_y=YPos.TOP)
                    self.set_y(row_y + row_h)
                else:
                    txt_color = GRAY_400 if is_done else (RED if is_overdue else DARK)
                    name_txt = _s(task["name"])
                    name_txt = name_txt[:44] + "..." if len(name_txt) > 44 else name_txt
                    w_norm = task.get("weight_norm")
                    w_pct_txt = f"{w_norm*100:.0f}%" if w_norm is not None else ""
                    # Passa célula Peso vazia — o overlay abaixo renderiza com a cor correta.
                    # Passar w_pct_txt aqui E no overlay causava sobreposição de texto.
                    self._table_row([
                        (name_txt,                         65, "L"),
                        ("",                               10, "C"),
                        (_s(task["status"] or "-")[:18],   33, "L"),
                        (asgn,                             46, "L"),
                        (task["due_date_fmt"],              28, "C"),
                    ], fill=even, text_color=txt_color, bold=(w_norm is not None and not is_done))
                    # Overlay único para o peso: azul (em aberto) ou cinza (concluído)
                    if w_pct_txt:
                        peso_color = GRAY_400 if is_done else BLUE_TXT
                        self.set_xy(14 + 65, row_y + 0.5)
                        self.set_font("Helvetica", style="B" if not is_done else "", size=6)
                        self._set_text(peso_color)
                        self.cell(10, 5, w_pct_txt, align="C")
                        self.set_y(row_y + 6)

    # ── Nota de rodapé final ─────────────────────────────────────────────────

    def build_footnote(self, data: dict) -> None:
        self.ln(8)
        self.set_draw_color(*GRAY_200)
        self.set_line_width(0.2)
        self.line(14, self.get_y(), 196, self.get_y())
        self.ln(3)
        self.set_font("Helvetica", size=7)
        self._set_text(GRAY_400)
        self.multi_cell(182, 4,
            f"Relatorio gerado automaticamente pelo sistema de gestao de projetos U2 Broadcast em {data['generated_at']}. "
            f"Os dados refletem o estado do cache local atualizado em {data['last_refresh_at']}. "
            "Para dados em tempo real, acesse o dashboard ou force uma atualizacao via POST /dashboard/refresh."
        )


# ── Serviço público ───────────────────────────────────────────────────────────

def _format_task_row(task, now: datetime) -> dict:
    import json as _json
    try:
        assignees = _json.loads(task.assignees_json or "[]")
    except Exception:
        assignees = []
    is_done = task.status_type in ("done", "closed")
    due_fmt = task.due_date.strftime("%d/%m/%Y") if task.due_date else "Sem prazo"
    is_overdue = task.due_date is not None and task.due_date < now and not is_done
    return {
        "task_id": task.task_id,
        "parent_task_id": task.parent_task_id,
        "name": task.name or "",
        "status": task.status or "",
        "status_type": task.status_type or "",
        "assignees_str": ", ".join(a.get("username") or "?" for a in assignees) or "N/D",
        "due_date_fmt": due_fmt,
        "is_overdue": is_overdue,
        "url": task.url,
    }


def _pct_color_name(rate: float) -> str:
    if rate >= 0.70:
        return "green"
    if rate >= 0.40:
        return "yellow"
    return "red"


class ReportService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = CacheRepository(db)

    async def generate_pdf(self, space_id: str) -> bytes:
        data = await self._build_data(space_id)
        return await asyncio.to_thread(self._render_pdf, data)

    async def _build_data(self, space_id: str) -> dict:
        space = await self._repo.get_space(space_id)
        space_name = space.name if space else space_id

        kpis_raw = await self._repo.get_overview_kpis(space_id)
        kpis = {**kpis_raw, "completion_pct": _pct(kpis_raw["completion_rate"])}

        folders_raw = await self._repo.get_folders_with_metrics(space_id)
        folders = []
        for folder in folders_raw:
            lists_raw = await self._repo.get_lists_with_metrics(folder["folder_id"])
            folders.append({
                **folder,
                "completion_pct": _pct(folder["completion_rate"]),
                "lists": [{**lst, "completion_pct": _pct(lst["completion_rate"])} for lst in lists_raw],
            })

        folderless_raw = await self._repo.get_lists_with_metrics(None, space_id)
        folderless_lists = [{**lst, "completion_pct": _pct(lst["completion_rate"])} for lst in folderless_raw]

        overdue_raw = await self._repo.get_overdue_tasks_detail(space_id, limit=30)
        overdue_tasks = [
            {
                **t,
                "due_date_fmt": t["due_date"].strftime("%d/%m/%Y") if t["due_date"] else "N/D",
                "assignees_str": ", ".join(t["assignees"]) or "N/D",
            }
            for t in overdue_raw
        ]

        upcoming_raw = await self._repo.get_upcoming_tasks(space_id, days=30)
        upcoming_tasks = []
        for t in upcoming_raw[:20]:
            due_fmt = "N/D"
            if t["due_date"]:
                try:
                    due_fmt = datetime.fromisoformat(t["due_date"]).strftime("%d/%m/%Y")
                except ValueError:
                    due_fmt = t["due_date"]
            upcoming_tasks.append({
                **t,
                "due_date_fmt": due_fmt,
                "assignees_str": ", ".join(t["assignees"]) if t["assignees"] else "N/D",
            })

        assignee_raw = await self._repo.get_assignee_task_stats(space_id)
        assignee_stats = []
        for a in assignee_raw:
            total = a["open"] + a["completed"]
            rate = a["completed"] / total if total > 0 else 0.0
            assignee_stats.append({
                **a,
                "total": total,
                "completion_rate": rate,
                "completion_pct": _pct(rate) if total > 0 else "N/D",
            })

        last_log = await self._repo.get_last_refresh()
        last_refresh = last_log.created_at.strftime("%d/%m/%Y as %H:%M") if last_log else "N/D"

        return {
            "space_name": space_name,
            "generated_at": datetime.utcnow().strftime("%d/%m/%Y as %H:%M"),
            "kpis": kpis,
            "folders": folders,
            "folderless_lists": folderless_lists,
            "overdue_tasks": overdue_tasks,
            "upcoming_tasks": upcoming_tasks,
            "assignee_stats": assignee_stats,
            "last_refresh_at": last_refresh,
        }

    @staticmethod
    def _render_pdf(data: dict) -> bytes:
        logger.debug("Gerando PDF com fpdf2")
        pdf = _Report(data["space_name"], data["generated_at"])
        pdf.alias_nb_pages()
        pdf.build_cover(data)
        pdf.build_executive_summary(data)
        pdf.build_project_health(data)
        pdf.build_overdue(data["overdue_tasks"])
        pdf.build_upcoming(data["upcoming_tasks"])
        pdf.build_team(data["assignee_stats"])
        pdf.build_footnote(data)
        return bytes(pdf.output())


class ProvinceReportService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = CacheRepository(db)

    async def generate_pdf(self, folder_id: str) -> bytes:
        data = await self._build_data(folder_id)
        return await asyncio.to_thread(self._render_pdf, data)

    async def _build_data(self, folder_id: str) -> dict:
        now = datetime.utcnow()

        folder = await self._repo.get_folder_by_id(folder_id)
        if not folder:
            raise ValueError(f"Pasta {folder_id} nao encontrada no cache")

        space = await self._repo.get_space(folder.space_id)
        space_name = space.name if space else folder.space_id

        kpis_raw = await self._repo.get_folder_kpis(folder_id)
        lists_metrics = await self._repo.get_lists_with_metrics(folder_id)

        # ── Pesos em dois níveis: tarefa (disciplina) + subtarefa (atividade) ──
        tasks_for_weights = await self._repo.get_tasks_for_weighted_progress(folder_id)
        weighted_data = compute_province_progress(tasks_for_weights)
        disciplines = weighted_data["disciplines"]
        weighted_progress = weighted_data["weighted_progress"]
        weights_configured = weighted_data["weights_configured"]

        # Lookup: task_id → peso normalizado dentro da lista
        task_weight_by_id: dict[str, float] = {}
        task_progress_by_id: dict[str, float] = {}
        for disc in disciplines:
            for td in disc.get("task_details", []):
                if td.get("task_id"):
                    task_weight_by_id[td["task_id"]] = td["weight_norm"]
                    task_progress_by_id[td["task_id"]] = td["progress"]

        # ── Detalhamento por lista (para páginas de detalhe no PDF) ───────────
        lists_detail = []
        for lst in lists_metrics:
            tasks_orm = await self._repo.get_tasks_by_list(lst["list_id"], include_subtasks=True)
            all_rows = {t.task_id: _format_task_row(t, now) for t in tasks_orm}
            subtasks_by_parent: dict[str, list] = {}
            for row in all_rows.values():
                if row["parent_task_id"]:
                    subtasks_by_parent.setdefault(row["parent_task_id"], []).append(row)
            ordered: list[dict] = []
            for row in all_rows.values():
                if not row["parent_task_id"]:
                    # Anexa peso e progresso ponderado ao pai
                    row["weight_norm"] = task_weight_by_id.get(row["task_id"])
                    row["task_progress"] = task_progress_by_id.get(row["task_id"])
                    ordered.append(row)
                    for sub in subtasks_by_parent.get(row["task_id"], []):
                        ordered.append(sub)
            # Usa completion_rate ponderada calculada para o header da lista
            disc_map = {d["list_id"]: d for d in disciplines}
            disc = disc_map.get(lst["list_id"], {})
            weighted_rate = disc.get("completion_rate", lst["completion_rate"])
            lists_detail.append({
                **lst,
                "completion_rate": weighted_rate,
                "completion_pct": _pct(weighted_rate),
                "tasks": ordered,
                "task_details": disc.get("task_details", []),
            })

        overdue_raw = await self._repo.get_overdue_tasks_by_folder(folder_id, limit=50)
        overdue_tasks = [
            {**t, "due_date_fmt": t["due_date"].strftime("%d/%m/%Y"), "assignees_str": ", ".join(t["assignees"]) or "N/D"}
            for t in overdue_raw
        ]

        upcoming_tasks = await self._repo.get_upcoming_tasks_by_folder(folder_id, days=60)

        assignee_raw = await self._repo.get_assignee_stats_by_folder(folder_id)
        assignee_stats = []
        for a in assignee_raw:
            total = a["open"] + a["completed"]
            rate = a["completed"] / total if total > 0 else 0.0
            assignee_stats.append({
                **a,
                "total": total,
                "completion_rate": rate,
                "completion_pct": _pct(rate) if total > 0 else "N/D",
            })

        last_log = await self._repo.get_last_refresh()
        last_refresh = last_log.created_at.strftime("%d/%m/%Y as %H:%M") if last_log else "N/D"

        # ── Listas com metadados de peso para tabela de resumo ───────────────
        weighted_by_list = {d["list_id"]: d for d in disciplines}
        lists_with_weight = []
        for lst in lists_metrics:
            disc = weighted_by_list.get(lst["list_id"], {})
            w_rate = disc.get("completion_rate", lst["completion_rate"])
            w_pct = disc.get("weight_pct")
            lists_with_weight.append({
                **lst,
                "completion_rate": w_rate,
                "completion_pct": _pct(w_rate),
                "weight": disc.get("weight"),
                "weight_pct": f"{w_pct:.1f}%" if w_pct is not None else None,
                "weighted_contribution": disc.get("weighted_contribution"),
            })

        # KPIs gerais usam progresso simples (contagem); capa usa ponderado
        kpis = {**kpis_raw, "completion_pct": _pct(kpis_raw["completion_rate"])}

        return {
            "folder_name": folder.name,
            "space_name": space_name,
            "generated_at": now.strftime("%d/%m/%Y as %H:%M"),
            "last_refresh_at": last_refresh,
            "total_lists": len(lists_metrics),
            "kpis": kpis,
            "lists": lists_with_weight,
            "lists_detail": lists_detail,
            "overdue_tasks": overdue_tasks,
            "upcoming_tasks": upcoming_tasks,
            "assignee_stats": assignee_stats,
            "disciplines": disciplines,
            "weighted_progress": weighted_progress,
            "weighted_progress_pct": _pct(weighted_progress) if weighted_progress is not None else None,
            "weights_configured": weights_configured,
        }

    @staticmethod
    def _render_pdf(data: dict) -> bytes:
        logger.debug(f"Gerando PDF de provincia: {data['folder_name']}")
        pdf = _Report(data["folder_name"], data["generated_at"])
        pdf.alias_nb_pages()
        pdf.build_cover_provincia(data)
        pdf.build_resumo_provincia(data)
        pdf.build_listas_detail(data["lists_detail"])
        if data["overdue_tasks"]:
            pdf.build_overdue(data["overdue_tasks"])
        if data["upcoming_tasks"]:
            pdf.build_upcoming(data["upcoming_tasks"])
        if data["assignee_stats"]:
            pdf.build_team(data["assignee_stats"])
        pdf.build_footnote(data)
        return bytes(pdf.output())


# ── Relatório Periódico (Diário / Semanal) ────────────────────────────────────

_PCOLS = [
    ("Tarefa",         91, "L"),
    ("Status",         28, "L"),
    ("Responsavel",    45, "L"),
    ("Data",           18, "C"),
]
_PCOL_W = (91, 28, 45, 18)  # name, status, resp, date (total = 182mm)


class _PeriodicReport(_Report):
    def __init__(self, space_name: str, generated_at: str, report_type: str) -> None:
        super().__init__(space_name, generated_at)
        self._report_type = report_type  # "Diario" or "Semanal"

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-12)
        self.set_font("Helvetica", size=7)
        self.set_text_color(*GRAY_400)
        self.cell(0, 4,
            f"U2 Broadcast  -  Relatorio {self._report_type} de Atualizacoes  -  Pagina {self.page_no()} de {{nb}}",
            align="C")

    def build_cover_periodic(self, data: dict) -> None:
        self.add_page()
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 210, 297, style="F")

        self.set_xy(18, 28)
        self.set_font("Helvetica", style="B", size=7)
        self.set_text_color(147, 197, 253)
        self.cell(0, 5, "U2 BROADCAST", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_fill_color(*BLUE)
        self.rect(18, 36, 18, 2.5, style="F")

        self.set_xy(18, 42)
        self.set_font("Helvetica", style="B", size=22)
        self._set_text(WHITE)
        self.multi_cell(174, 9, f"Relatorio {_s(data['report_type'])}\nde Atualizacoes", align="L")

        self.set_xy(18, 66)
        self.set_font("Helvetica", size=13)
        self.set_text_color(147, 197, 253)
        self.cell(0, 8, _s(data["period_label"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_draw_color(37, 99, 235)
        self.set_line_width(0.3)
        self.line(18, 80, 192, 80)

        kw, kh, gap = 40, 22, 3
        kpis_cover = [
            (str(data["n_provinces"]), "PROVINCIAS COM UPDATES"),
            (str(data["n_concluded"]), "TAREFAS CONCLUIDAS"),
            (str(data["n_created"]),   "NOVAS TAREFAS"),
            (str(data["n_updated"]),   "ATUALIZACOES"),
        ]
        for i, (val, lbl) in enumerate(kpis_cover):
            kx = 18 + i * (kw + gap)
            ky = 86
            self.set_fill_color(40, 70, 115)
            self.set_draw_color(70, 100, 160)
            self.set_line_width(0.3)
            self.rect(kx, ky, kw, kh, style="FD")
            self.set_xy(kx, ky + 3)
            self.set_font("Helvetica", style="B", size=16)
            self._set_text(WHITE)
            self.cell(kw, 8, val, align="C", new_x=XPos.LEFT, new_y=YPos.NEXT)
            self.set_xy(kx, ky + 13)
            self.set_font("Helvetica", size=5)
            self.set_text_color(147, 197, 253)
            self.cell(kw, 4, lbl, align="C")

        y0 = 118
        meta = [
            ("DATA DE GERACAO", data["generated_at"] + " (UTC)"),
            ("ULTIMA ATUALIZACAO DOS DADOS", data["last_refresh_at"]),
            ("ESPACO", _s(data["space_name"])),
        ]
        for label, value in meta:
            self.set_xy(18, y0)
            self.set_font("Helvetica", size=7)
            self.set_text_color(191, 219, 254)
            self.cell(0, 4, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_xy(18, y0 + 5)
            self.set_font("Helvetica", style="B", size=9)
            self._set_text(WHITE)
            self.cell(0, 5, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            y0 += 14

        self.set_draw_color(255, 255, 255)
        self.set_line_width(0.1)
        self.line(18, 265, 192, 265)
        self.set_xy(18, 268)
        self.set_font("Helvetica", size=7)
        self.set_text_color(96, 165, 250)
        self.multi_cell(174, 4,
            "Documento gerado automaticamente pelo sistema de gestao de projetos U2 Broadcast.\n"
            "Este relatorio apresenta apenas tarefas com atividade no periodo indicado acima.",
            align="L",
        )

    def _render_list_subheader(self, list_name: str, n_tasks: int, n_subs: int = 0) -> None:
        y, h = self.get_y(), 6.5
        self.set_fill_color(*BLUE_BG)
        self.rect(14, y, 182, h, style="F")
        self.set_fill_color(*NAVY)
        self.rect(14, y, 2, h, style="F")
        self.set_xy(18, y + 1.5)
        self.set_font("Helvetica", style="B", size=7)
        self._set_text(BLUE_TXT)
        self.cell(150, 4, _s(list_name.upper()), align="L")
        info = f"{n_tasks} tarefa(s)" + (f"  ·  {n_subs} subtarefa(s)" if n_subs else "")
        self.set_xy(14, y + 1.5)
        self.set_font("Helvetica", size=6)
        self._set_text(GRAY_400)
        self.cell(180, 4, info, align="R")
        self.set_y(y + h)

    def _render_task_entry(self, task: dict, row_idx: int) -> None:
        """Renderiza uma tarefa: linha principal + descrição (opcional) + subtarefas indentadas."""
        name_w, status_w, resp_w, date_w = _PCOL_W
        is_done = task.get("category") == "concluded"
        txt_color = GRAY_400 if is_done else DARK
        even = (row_idx % 2 == 0)

        name_txt = _s(task["name"])
        name_txt = name_txt[:60] + "..." if len(name_txt) > 60 else name_txt
        date_ref = task.get("date_ref")
        date_str = date_ref.strftime("%d/%m/%Y") if date_ref else "—"

        self._table_row([
            (name_txt,                   name_w,   "L"),
            (_s(task["status"])[:18],     status_w, "L"),
            (task["assignees_str"][:28],  resp_w,   "L"),
            (date_str,                   date_w,   "C"),
        ], fill=even, text_color=txt_color, bold=(not is_done))

        # Descrição em itálico cinza
        desc = task.get("description", "").strip()
        if desc:
            self.set_xy(16, self.get_y())
            self.set_font("Helvetica", "I", size=6)
            self._set_text(GRAY_400)
            self.cell(178, 3.5, _s(desc[:200]), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(0.5)

        # Subtarefas indentadas (x=23, 9mm de recuo da margem)
        for sub in task.get("subtasks", []):
            sub_y = self.get_y()
            sub_done = sub.get("category") == "concluded"
            sub_color = GRAY_400 if sub_done else GRAY_600
            sub_date = sub["date_ref"].strftime("%d/%m/%Y") if sub.get("date_ref") else "—"
            sub_name = _s(sub["name"])
            sub_name = sub_name[:64] + "..." if len(sub_name) > 64 else sub_name

            self.set_fill_color(180, 185, 210)
            self.rect(20, sub_y + 0.8, 0.8, 3.4, style="F")

            self.set_font("Helvetica", size=7)
            self._set_text(sub_color)
            self.set_xy(23, sub_y + 0.8)
            # name_w - 9 = 97mm (recuo de 9mm na coluna de nome)
            self.cell(name_w - 9, 4, sub_name, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.cell(status_w,   4, _s(sub["status"])[:18], align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.cell(resp_w,     4, sub["assignees_str"][:28], align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
            self.cell(date_w,     4, sub_date, align="C", new_x=XPos.LMARGIN, new_y=YPos.TOP)
            self.set_y(sub_y + 5)

    def build_province_updates(self, folder_data: dict, period_label: str) -> None:
        from collections import defaultdict

        tasks = folder_data["tasks"]
        concluded = [t for t in tasks if t["category"] == "concluded"]
        created   = [t for t in tasks if t["category"] == "created"]
        updated   = [t for t in tasks if t["category"] == "updated"]
        n_sub = sum(len(t.get("subtasks", [])) for t in tasks)

        self.add_page()
        subtitle_parts = f"{len(concluded)} concluidas · {len(created)} criadas · {len(updated)} atualizadas"
        if n_sub:
            subtitle_parts += f" · {n_sub} subtarefa(s)"
        self._section_header(
            f"Provincia: {_s(folder_data['folder_name'])}",
            f"Periodo: {_s(period_label)}  ·  {subtitle_parts}",
        )

        cat_groups = [
            (concluded, f"Concluidas no periodo ({len(concluded)})", GREEN),
            (created,   f"Criadas no periodo ({len(created)})",      BLUE),
            (updated,   f"Atualizadas no periodo ({len(updated)})",  AMBER),
        ]

        folder_name = folder_data["folder_name"]

        for cat_tasks, cat_label, cat_color in cat_groups:
            if not cat_tasks:
                continue

            cat_y = self.get_y()
            if cat_y > 248:
                self.add_page()
                self._section_header(f"Provincia: {_s(folder_name)} (cont.)")
                cat_y = self.get_y()

            self.set_fill_color(*cat_color)
            self.rect(14, cat_y, 3, 7, style="F")
            self.set_fill_color(*GRAY_50)
            self.rect(17, cat_y, 179, 7, style="F")
            self.set_xy(20, cat_y + 1.5)
            self.set_font("Helvetica", style="B", size=7)
            self._set_text(DARK)
            self.cell(0, 4, cat_label.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1)

            by_list: dict[str, list] = defaultdict(list)
            for t in cat_tasks:
                by_list[t["list_name"]].append(t)

            for list_name, list_tasks in by_list.items():
                n_subs = sum(len(t.get("subtasks", [])) for t in list_tasks)

                if self.get_y() > 252:
                    self.add_page()
                    self._section_header(f"Provincia: {_s(folder_name)} (cont.)")

                self._render_list_subheader(list_name, len(list_tasks), n_subs)
                self._table_header(_PCOLS)

                row_idx = 0
                for task in list_tasks:
                    needed = 6.0
                    if task.get("description", "").strip():
                        needed += 4.0
                    needed += len(task.get("subtasks", [])) * 5.0

                    if self.get_y() + needed > 258:
                        self.add_page()
                        self._section_header(f"Provincia: {_s(folder_name)} (cont.)")
                        self._render_list_subheader(list_name, len(list_tasks), n_subs)
                        self._table_header(_PCOLS)
                        row_idx = 0

                    self._render_task_entry(task, row_idx)
                    row_idx += 1

                self.ln(2)

            self.ln(3)

    def build_no_updates(self, period_label: str) -> None:
        self.add_page()
        self._section_header("Sem Atualizacoes", f"Nenhuma tarefa foi alterada no periodo: {_s(period_label)}")
        self.ln(10)
        self.set_font("Helvetica", "I", size=10)
        self._set_text(GRAY_400)
        self.cell(182, 10, "Nenhuma atividade registrada no periodo.", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)


class PeriodicReportService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = CacheRepository(db)

    async def generate_daily_pdf(self, space_id: str) -> bytes:
        from datetime import timedelta
        now = datetime.utcnow()
        since = now - timedelta(days=1)
        data = await self._build_data(space_id, since, now, "Diario",
                                      f"Dia {now.strftime('%d/%m/%Y')}")
        return await asyncio.to_thread(self._render_pdf, data)

    async def generate_weekly_pdf(self, space_id: str) -> bytes:
        from datetime import timedelta
        now = datetime.utcnow()
        # Retrocede ao domingo mais recente às 00:00:00
        # weekday(): segunda=0 … domingo=6 → (weekday+1)%7 dias atrás chega no domingo
        days_since_sunday = (now.weekday() + 1) % 7
        since = (now - timedelta(days=days_since_sunday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        period_label = f"Semana de {since.strftime('%d/%m/%Y')} a {now.strftime('%d/%m/%Y')}"
        data = await self._build_data(space_id, since, now, "Semanal", period_label)
        return await asyncio.to_thread(self._render_pdf, data)

    async def _build_data(self, space_id: str, since: datetime, until: datetime,
                          report_type: str, period_label: str) -> dict:
        space = await self._repo.get_space(space_id)
        space_name = space.name if space else space_id

        folders_data = await self._repo.get_period_updates(space_id, since, until)
        folders_data = [f for f in folders_data if f["tasks"]]

        n_concluded = sum(1 for f in folders_data for t in f["tasks"] if t["category"] == "concluded")
        n_created   = sum(1 for f in folders_data for t in f["tasks"] if t["category"] == "created")
        n_updated   = sum(1 for f in folders_data for t in f["tasks"] if t["category"] == "updated")

        last_log = await self._repo.get_last_refresh()
        last_refresh = last_log.created_at.strftime("%d/%m/%Y as %H:%M") if last_log else "N/D"

        return {
            "space_name": space_name,
            "generated_at": until.strftime("%d/%m/%Y as %H:%M"),
            "last_refresh_at": last_refresh,
            "report_type": report_type,
            "period_label": period_label,
            "n_provinces": len(folders_data),
            "n_concluded": n_concluded,
            "n_created": n_created,
            "n_updated": n_updated,
            "folders": folders_data,
        }

    @staticmethod
    def _render_pdf(data: dict) -> bytes:
        logger.debug(f"Gerando PDF {data['report_type']}: {data['period_label']}")
        pdf = _PeriodicReport(data["space_name"], data["generated_at"], data["report_type"])
        pdf.alias_nb_pages()
        pdf.build_cover_periodic(data)
        if data["folders"]:
            for folder in data["folders"]:
                pdf.build_province_updates(folder, data["period_label"])
        else:
            pdf.build_no_updates(data["period_label"])
        pdf.build_footnote(data)
        return bytes(pdf.output())
