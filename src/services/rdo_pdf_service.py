"""Geração de PDF para Relatório Diário de Obra Civil (RDO)."""
from datetime import datetime
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from src.services.progress_service import SiteProgressResult

# ── Paleta (mesma de report_service.py) ─────────────────────────────────────
NAVY    = (27,  58, 107)
BLUE    = (59, 130, 246)
GREEN   = (22, 163,  74)
RED     = (220,  38,  38)
AMBER   = (217, 119,   6)
WHITE   = (255, 255, 255)
GRAY_50 = (248, 250, 252)
GRAY_200= (226, 232, 240)
GRAY_400= (148, 163, 184)
GRAY_600= ( 71,  85, 105)
DARK    = ( 15,  23,  42)

_LATIN1_MAP = {
    ord("—"): "-", ord("–"): "-", ord("…"): "...",
    ord("'"): "'", ord("'"): "'", ord("“"): '"', ord("”"): '"',
    ord("•"): "*", ord("▸"): ">", ord("→"): "->",
}


def _s(text: str | None) -> str:
    if not text:
        return ""
    return str(text).translate(_LATIN1_MAP)


def _bool_label(val) -> str:
    if val is True or val == "true":
        return "Sim"
    if val is False or val == "false":
        return "Nao"
    return "-"


QUALITY_LABELS = {
    "epi": "Uso de EPI",
    "limpeza": "Limpeza e organizacao do local",
    "conformidade_projeto": "Servicos conforme projeto",
    "ensaios": "Ensaios/testes realizados",
    "nao_conformidades": "Nao conformidades registadas",
}

SIG_LABELS = {
    "responsavel_obra": "Responsavel da Obra",
    "fiscal_supervisor": "Fiscal / Supervisor",
    "representante_cliente": "Representante do Cliente",
}


class _RdoPDF(FPDF):
    def __init__(self, site_name: str, report_number: int, report_date: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.site_name = _s(site_name)
        self.report_number = report_number
        self.report_date = report_date
        self.generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(left=14, top=16, right=14)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 3, 6, style="F")
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*GRAY_400)
        self.set_xy(14, 4)
        self.cell(0, 4, f"RDO no {self.report_number} - {self.site_name} - {self.report_date}", align="L")
        self.set_xy(-50, 4)
        self.cell(36, 4, f"Gerado em: {self.generated_at}", align="R")
        self.ln(8)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_draw_color(*GRAY_200)
        self.set_line_width(0.3)
        self.line(14, self.get_y(), 196, self.get_y())
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*GRAY_400)
        self.cell(0, 5, f"Pagina {self.page_no()}", align="C")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def section_header(self, title: str) -> None:
        self.set_fill_color(*NAVY)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 9)
        self.set_x(14)
        self.cell(182, 7, f"  {_s(title)}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def kv_row(self, pairs: list[tuple[str, str]], col_w: float = 60.7) -> None:
        """Renderiza uma linha de pares label:valor em colunas."""
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*GRAY_400)
        x0 = 14
        for label, _ in pairs:
            self.set_x(x0)
            self.cell(col_w, 4, _s(label).upper(), new_x=XPos.RIGHT, new_y=YPos.TOP)
            x0 += col_w
        self.ln(4)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*DARK)
        x0 = 14
        for _, value in pairs:
            self.set_x(x0)
            self.cell(col_w, 5, _s(value) or "-", new_x=XPos.RIGHT, new_y=YPos.TOP)
            x0 += col_w
        self.ln(7)

    def table_header(self, cols: list[tuple[str, float]]) -> None:
        self.set_font("Helvetica", "B", 7.5)
        self.set_fill_color(*GRAY_50)
        self.set_text_color(*GRAY_600)
        self.set_draw_color(*GRAY_200)
        self.set_line_width(0.2)
        self.set_x(14)
        for label, w in cols:
            self.cell(w, 6, _s(label), border="B", fill=True)
        self.ln()

    def table_row(self, cols: list[tuple[str, float]], shade: bool = False) -> None:
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*DARK)
        self.set_fill_color(*GRAY_50 if shade else WHITE)
        self.set_draw_color(*GRAY_200)
        self.set_line_width(0.1)
        line_height = 4.5
        # Calculate exact wrapped line count per cell (accounts for word-wrap boundaries)
        max_lines = 1
        for text, w in cols:
            wrapped = self.multi_cell(w, line_height, _s(text), dry_run=True, output="LINES")
            max_lines = max(max_lines, len(wrapped))
        row_h = max_lines * line_height
        self.set_x(14)
        for text, w in cols:
            self.multi_cell(w, row_h, _s(text), border="B", fill=shade, max_line_height=line_height, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln(row_h)

    def kpi_box(self, label: str, value: str, color: tuple = NAVY, x: float = 14, w: float = 36) -> None:
        y = self.get_y()
        self.set_fill_color(*color)
        self.rect(x, y, w, 14, style="F")
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 14)
        self.set_xy(x, y + 1)
        self.cell(w, 7, _s(value), align="C")
        self.set_font("Helvetica", "", 6.5)
        self.set_xy(x, y + 8)
        self.cell(w, 4, _s(label).upper(), align="C")
        self.set_y(y)

    def text_block(self, text: str, label: str | None = None) -> None:
        if label:
            self.set_font("Helvetica", "B", 7)
            self.set_text_color(*GRAY_400)
            self.set_x(14)
            self.cell(0, 4, _s(label).upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*DARK)
        self.set_fill_color(*GRAY_50)
        self.set_x(14)
        self.multi_cell(182, 5, _s(text) or "-", border=1, fill=True)
        self.ln(3)


# ── Progresso EVM (mesma lógica da aba 02_Progresso da planilha PMEx) ─────────

MARCO_LEGEND = "Legenda MARCO: 0 = nao iniciado  |  1 = preparacao/escavacao  |  2 = estrutura/forma  |  3 = execucao principal  |  4 = concluido/liberado"


def _pct_str(value: float) -> str:
    return f"{value * 100:.1f}%"


def _render_progress_sections(
    pdf: "_RdoPDF",
    project_progress: list[SiteProgressResult],
    current_site_id: int | None,
    until_label: str,
    advance_label: str,
    start_col_label: str,
    end_col_label: str,
    summary_title: str = "1.12 Resumo de Progresso por Site (Projeto)",
    detail_title_prefix: str = "1.13 Medicao Objetiva de Progresso -",
) -> None:
    """Renderiza 'Resumo de Progresso por Site' (todos os sites do projeto, mesmo
    os sem avanco no periodo) e 'Medicao Objetiva de Progresso' (atividades do site
    do relatorio), espelhando a aba 02_Progresso da planilha de referencia."""
    if not project_progress:
        return

    # ── Resumo de Progresso por Site ────────────────────────────────────────
    pdf.section_header(summary_title)
    cols = [
        ("Site", 40), ("Perfil", 40), (until_label, 34),
        (advance_label, 34), ("Progresso Acumulado", 34),
    ]
    pdf.table_header(cols)
    for i, sp in enumerate(project_progress):
        pdf.table_row([
            (_s(sp.site_name), 40),
            (_s(sp.profile_name) or "-", 40),
            (_pct_str(sp.progress_yesterday), 34),
            (_pct_str(sp.day_advance), 34),
            (_pct_str(sp.progress_today), 34),
        ], shade=i % 2 == 0)
    pdf.ln(3)

    # ── Medicao Objetiva de Progresso (site do relatorio) ───────────────────
    current = next((sp for sp in project_progress if sp.site_id == current_site_id), None)
    if current and current.activities:
        pdf.section_header(f"{detail_title_prefix} {_s(current.site_name)}")
        cols = [
            ("Categoria", 26), ("Atividade", 48), ("Un.", 10), ("Qtd.", 14),
            (start_col_label, 16), (end_col_label, 16),
            ("% Ant.", 14), ("% Atu.", 14), ("Avanco", 14), ("Marco", 10),
        ]
        pdf.table_header(cols)
        for i, a in enumerate(current.activities):
            pdf.table_row([
                (_s(a.category_name), 26),
                (_s(a.activity_name), 48),
                (_s(a.unit) or "-", 10),
                (f"{a.total_qty:g}", 14),
                (f"{a.qty_yesterday:g}", 16),
                (f"{a.qty_today:g}", 16),
                (_pct_str(a.pct_yesterday), 14),
                (_pct_str(a.pct_today), 14),
                (_pct_str(a.day_advance), 14),
                (str(a.marco) if a.marco is not None else "-", 10),
            ], shade=i % 2 == 0)
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 6.5)
        pdf.set_text_color(*GRAY_400)
        pdf.set_x(14)
        pdf.cell(0, 4, MARCO_LEGEND, align="L")
        pdf.ln(6)


# ── Geração principal ────────────────────────────────────────────────────────

def generate_rdo_pdf(
    report: dict,
    site_name: str = "",
    project_progress: list[SiteProgressResult] | None = None,
) -> bytes:
    """Gera PDF do RDO e retorna os bytes."""
    pdf = _RdoPDF(
        site_name=site_name or report.get("local_site") or f"Site {report.get('site_id', '')}",
        report_number=report.get("report_number", 0),
        report_date=report.get("date", ""),
    )

    # ── Capa ─────────────────────────────────────────────────────────────────
    pdf.add_page()

    # Faixa superior NAVY
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, 210, 40, style="F")
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_xy(14, 10)
    pdf.cell(0, 10, "RELATORIO DIARIO DE OBRA CIVIL", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_x(14)
    pdf.cell(0, 6, f"RDO no {report.get('report_number', '')}  |  {_s(site_name)}  |  {report.get('date', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_xy(14, 50)

    # ── 1.1 Identificação ────────────────────────────────────────────────────
    pdf.section_header("1.1 Identificacao")
    pdf.kv_row([
        ("Provincia", report.get("province")),
        ("Local / Site", report.get("local_site")),
        ("Responsavel de Obra", report.get("responsible")),
    ])
    pdf.kv_row([
        ("Empreiteiro / Equipa", report.get("contractor")),
        ("Fiscal / Supervisor", report.get("supervisor")),
        ("Condicoes Climaticas", report.get("weather_conditions")),
    ])
    pdf.kv_row([
        ("Situacao Geral", report.get("general_situation")),
        ("Hora Inicio", report.get("start_time")),
        ("Hora Termino", report.get("end_time")),
    ])
    pdf.ln(2)

    # ── 1.2 Resumo do Dia ────────────────────────────────────────────────────
    pdf.section_header("1.2 Resumo do Dia")
    y = pdf.get_y() + 2
    kpi_w = 36
    gap = 0.4
    kpis = [
        ("Frentes Ativas", str(report.get("active_fronts") or 0), NAVY),
        ("Ativ. Concluidas", str(report.get("activities_completed") or 0), GREEN),
        ("Ativ. em Curso", str(report.get("activities_in_progress") or 0), BLUE),
        ("Restricoes", str(report.get("restrictions_count") or 0), AMBER if (report.get("restrictions_count") or 0) > 0 else GRAY_400),
        ("Total Pessoal", str(report.get("total_personnel") or 0), NAVY),
    ]
    x = 14.0
    for label, value, color in kpis:
        pdf.kpi_box(label, value, color, x=x, w=kpi_w)
        x += kpi_w + gap
    pdf.ln(17)

    # Seg./Saúde + Qualidade
    pdf.kv_row([
        ("Seg. / Saude", report.get("safety_situation")),
        ("Qualidade", report.get("quality_situation")),
        ("", ""),
    ])

    if report.get("short_comment"):
        pdf.text_block(report["short_comment"], label="Comentario do Dia")
    pdf.ln(1)

    # ── 1.3 Recursos Mobilizados ─────────────────────────────────────────────
    resources = [r for r in (report.get("resources") or []) if r.get("quantity", 0) > 0]
    if resources:
        pdf.section_header("1.3 Recursos Mobilizados")
        cols = [("Disciplina", 80), ("Quantidade", 30), ("Observacoes", 72)]
        pdf.table_header(cols)
        total_qty = 0
        for i, r in enumerate(resources):
            pdf.table_row([
                (r.get("discipline") or "", 80),
                (str(r.get("quantity") or 0), 30),
                (r.get("observations") or "", 72),
            ], shade=i % 2 == 0)
            total_qty += r.get("quantity") or 0
        # Total row
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*DARK)
        pdf.set_x(14)
        pdf.cell(80, 6, "TOTAL")
        pdf.cell(30, 6, str(total_qty))
        pdf.ln(8)

    # ── 1.4 Atividades ───────────────────────────────────────────────────────
    activities = report.get("activities") or []
    if activities:
        pdf.section_header("1.4 Atividades Civis Executadas")
        cols = [("Frente", 30), ("Categoria", 35), ("Atividade", 60), ("Un.", 14), ("Qtd.", 18), ("Status", 25)]
        pdf.table_header(cols)
        for i, a in enumerate(activities):
            pdf.table_row([
                (a.get("front_site") or "", 30),
                (a.get("civil_category") or "", 35),
                (a.get("activity_description") or "", 60),
                (a.get("unit") or "", 14),
                (str(a.get("qty_day") or ""), 18),
                (a.get("status") or "", 25),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── 1.5 Materiais ────────────────────────────────────────────────────────
    materials = report.get("materials") or []
    if materials:
        pdf.section_header("1.5 Materiais Recebidos / Aplicados")
        cols = [("Material / Equipamento", 65), ("Un.", 14), ("Qtd. Recebida", 28), ("Qtd. Aplicada", 28), ("Saldo", 22), ("Obs.", 25)]
        pdf.table_header(cols)
        for i, m in enumerate(materials):
            pdf.table_row([
                (m.get("material_name") or "", 65),
                (m.get("unit") or "", 14),
                (str(m.get("qty_received") or 0), 28),
                (str(m.get("qty_applied") or 0), 28),
                (str(m.get("balance") or 0), 22),
                (m.get("observations") or "", 25),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── 1.6 Ocorrências ──────────────────────────────────────────────────────
    occurrences = report.get("occurrences") or []
    if occurrences:
        pdf.section_header("1.6 Ocorrencias, Impedimentos e Riscos")
        cols = [("Tipo", 28), ("Descricao", 50), ("Impacto", 30), ("Acao Corretiva", 40), ("Resp.", 34)]
        pdf.table_header(cols)
        for i, o in enumerate(occurrences):
            pdf.table_row([
                (o.get("occurrence_type") or "", 28),
                (o.get("description") or "", 50),
                (o.get("impact") or "", 30),
                (o.get("corrective_action") or "", 40),
                (o.get("responsible") or "", 34),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── 1.7 Qualidade / Segurança ────────────────────────────────────────────
    quality_checks = report.get("quality_checks") or []
    if quality_checks:
        pdf.section_header("1.7 Qualidade, Seguranca e Conformidade")
        cols = [("Item de Verificacao", 110), ("Resultado", 30), ("Observacoes", 42)]
        pdf.table_header(cols)
        for i, q in enumerate(quality_checks):
            label = QUALITY_LABELS.get(q.get("check_type") or "", q.get("check_type") or "")
            pdf.table_row([
                (label, 110),
                (_bool_label(q.get("result")), 30),
                (q.get("observations") or "", 42),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── 1.9 Planeamento D+1 ──────────────────────────────────────────────────
    plans = report.get("next_day_plans") or []
    if plans:
        pdf.section_header("1.9 Planeamento para o Dia Seguinte")
        cols = [("Frente/Site", 40), ("Atividade Prevista", 72), ("Responsavel", 40), ("Dependencia", 30)]
        pdf.table_header(cols)
        for i, p in enumerate(plans):
            pdf.table_row([
                (p.get("front_site") or "", 40),
                (p.get("planned_activity") or "", 72),
                (p.get("responsible") or "", 40),
                (p.get("dependency") or "", 30),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── 1.10 Conclusão ───────────────────────────────────────────────────────
    if report.get("daily_conclusion"):
        pdf.section_header("1.10 Conclusao Diaria do Responsavel")
        pdf.ln(1)
        pdf.text_block(report["daily_conclusion"])

    # ── 1.11 Assinaturas ─────────────────────────────────────────────────────
    signatures = report.get("signatures") or []
    sig_with_data = [s for s in signatures if s.get("name")]
    if sig_with_data:
        pdf.section_header("1.11 Assinaturas")
        cols = [("Funcao", 60), ("Nome", 82), ("Data/Hora Confirmacao", 40)]
        pdf.table_header(cols)
        for i, s in enumerate(sig_with_data):
            confirmed = ""
            if s.get("confirmed_at"):
                try:
                    dt = datetime.fromisoformat(s["confirmed_at"])
                    confirmed = dt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    confirmed = _s(s["confirmed_at"])
            role_label = SIG_LABELS.get(s.get("role") or "", s.get("role") or "")
            pdf.table_row([
                (role_label, 60),
                (s.get("name") or "", 82),
                (confirmed, 40),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── 1.12 / 1.13 Progresso de Obra (EVM) ──────────────────────────────────
    _render_progress_sections(
        pdf, project_progress or [], report.get("site_id"),
        until_label="Progresso Ate Ontem", advance_label="Avanco do Dia",
        start_col_label="Ontem", end_col_label="Hoje",
    )

    # Rodapé de geração
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*GRAY_400)
    pdf.set_x(14)
    pdf.cell(0, 5, f"Documento gerado automaticamente em {pdf.generated_at} | U2 Broadcast", align="C")

    return bytes(pdf.output())


# ── Relatório semanal ────────────────────────────────────────────────────────

class _WeeklyRdoPDF(_RdoPDF):
    """Variante do _RdoPDF com cabeçalho adaptado para o relatório semanal."""

    def __init__(self, site_name: str, week_label: str) -> None:
        super().__init__(site_name=site_name, report_number=0, report_date=week_label)
        self.week_label = week_label

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 3, 6, style="F")
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*GRAY_400)
        self.set_xy(14, 4)
        self.cell(0, 4, f"Relatorio Semanal - {self.site_name} - {_s(self.week_label)}", align="L")
        self.set_xy(-50, 4)
        self.cell(36, 4, f"Gerado em: {self.generated_at}", align="R")
        self.ln(8)


def generate_weekly_rdo_pdf(
    reports: list[dict],
    site_name: str,
    week_label: str,
    project_progress: list[SiteProgressResult] | None = None,
) -> bytes:
    """Gera PDF consolidado dos RDOs de uma semana para um site."""
    from datetime import date as _date

    def _fmt_date(iso: str, fmt: str = "%d/%m/%Y") -> str:
        try:
            return _date.fromisoformat(iso).strftime(fmt)
        except Exception:
            return iso

    pdf = _WeeklyRdoPDF(site_name=site_name, week_label=week_label)

    # ── Capa ─────────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, 210, 40, style="F")
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_xy(14, 10)
    pdf.cell(0, 10, "RELATORIO SEMANAL DE OBRA CIVIL", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_x(14)
    pdf.cell(0, 6, f"{_s(site_name)}  |  Semana: {_s(week_label)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    total_personnel = sum(r.get("total_personnel") or 0 for r in reports)
    total_acts_completed = sum(r.get("activities_completed") or 0 for r in reports)
    total_occurrences = sum(len(r.get("occurrences") or []) for r in reports)

    pdf.set_xy(14, 55)

    # ── Resumo da Semana ─────────────────────────────────────────────────────
    pdf.section_header("Resumo da Semana")
    # cols sum = 26+14+20+20+26+26+22+28 = 182
    cols = [
        ("Data", 26), ("RDO#", 14), ("Frentes", 20), ("Pessoal", 20),
        ("Ativ. Concl.", 26), ("Ativ. Curso", 26), ("Restricoes", 22), ("Situacao", 28),
    ]
    pdf.table_header(cols)
    for i, r in enumerate(reports):
        pdf.table_row([
            (_fmt_date(r.get("date", "")), 26),
            (str(r.get("report_number", "-")), 14),
            (str(r.get("active_fronts") or 0), 20),
            (str(r.get("total_personnel") or 0), 20),
            (str(r.get("activities_completed") or 0), 26),
            (str(r.get("activities_in_progress") or 0), 26),
            (str(r.get("restrictions_count") or 0), 22),
            (_s(r.get("general_situation") or "-"), 28),
        ], shade=i % 2 == 0)

    # Linha de totais
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*DARK)
    pdf.set_x(14)
    pdf.cell(26 + 14, 6, "TOTAL SEMANA")
    pdf.cell(20, 6, "-")
    pdf.cell(20, 6, str(total_personnel))
    pdf.cell(26, 6, str(total_acts_completed))
    pdf.ln(10)

    # KPI boxes
    y = pdf.get_y()
    kpi_w, gap = 40, 2.0
    kpis = [
        ("RDOs no Periodo", str(len(reports)), NAVY),
        ("Total Pessoal", str(total_personnel), BLUE),
        ("Ativ. Concluidas", str(total_acts_completed), GREEN),
        ("Ocorrencias", str(total_occurrences), RED if total_occurrences > 0 else GRAY_400),
    ]
    x = 14.0
    for label, value, color in kpis:
        pdf.kpi_box(label, value, color, x=x, w=kpi_w)
        x += kpi_w + gap
    pdf.ln(20)

    # ── Atividades Executadas na Semana ──────────────────────────────────────
    all_activities = [
        (_fmt_date(r.get("date", ""), "%d/%m"), a)
        for r in reports
        for a in (r.get("activities") or [])
    ]
    if all_activities:
        pdf.section_header("Atividades Executadas na Semana")
        # cols sum = 16+28+30+55+12+18+23 = 182
        cols = [("Data", 16), ("Frente", 28), ("Categoria", 30), ("Atividade", 55), ("Un.", 12), ("Qtd.", 18), ("Status", 23)]
        pdf.table_header(cols)
        for i, (date_fmt, a) in enumerate(all_activities):
            pdf.table_row([
                (date_fmt, 16),
                (_s(a.get("front_site") or ""), 28),
                (_s(a.get("civil_category") or ""), 30),
                (_s(a.get("activity_description") or ""), 55),
                (_s(a.get("unit") or ""), 12),
                (str(a.get("qty_day") or ""), 18),
                (_s(a.get("status") or ""), 23),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── Ocorrências da Semana ────────────────────────────────────────────────
    all_occurrences = [
        (_fmt_date(r.get("date", ""), "%d/%m"), o)
        for r in reports
        for o in (r.get("occurrences") or [])
    ]
    if all_occurrences:
        pdf.section_header("Ocorrencias e Impedimentos da Semana")
        # cols sum = 16+26+52+36+52 = 182
        cols = [("Data", 16), ("Tipo", 26), ("Descricao", 52), ("Impacto", 36), ("Responsavel", 52)]
        pdf.table_header(cols)
        for i, (date_fmt, o) in enumerate(all_occurrences):
            pdf.table_row([
                (date_fmt, 16),
                (_s(o.get("occurrence_type") or ""), 26),
                (_s(o.get("description") or ""), 52),
                (_s(o.get("impact") or ""), 36),
                (_s(o.get("responsible") or ""), 52),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── Planeamento — último dia da semana ───────────────────────────────────
    last_plans = (reports[-1].get("next_day_plans") or []) if reports else []
    if last_plans:
        pdf.section_header("Planeamento — Proximo Periodo")
        # cols sum = 40+72+40+30 = 182
        cols = [("Frente/Site", 40), ("Atividade Prevista", 72), ("Responsavel", 40), ("Dependencia", 30)]
        pdf.table_header(cols)
        for i, p in enumerate(last_plans):
            pdf.table_row([
                (_s(p.get("front_site") or ""), 40),
                (_s(p.get("planned_activity") or ""), 72),
                (_s(p.get("responsible") or ""), 40),
                (_s(p.get("dependency") or ""), 30),
            ], shade=i % 2 == 0)
        pdf.ln(3)

    # ── Progresso de Obra (EVM) ───────────────────────────────────────────────
    current_site_id = reports[0].get("site_id") if reports else None
    _render_progress_sections(
        pdf, project_progress or [], current_site_id,
        until_label="Ate Inicio da Semana", advance_label="Avanco da Semana",
        start_col_label="Ini. Sem.", end_col_label="Fim Sem.",
        summary_title="Resumo de Progresso por Site (Projeto)",
        detail_title_prefix="Medicao Objetiva de Progresso -",
    )

    # Rodapé de geração
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*GRAY_400)
    pdf.set_x(14)
    pdf.cell(0, 5, f"Documento gerado automaticamente em {pdf.generated_at} | U2 Broadcast", align="C")

    return bytes(pdf.output())
