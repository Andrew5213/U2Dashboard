"""Geração de .xlsx para o RDO (Relatório Diário de Obra Civil), espelhando as
mesmas seções e ordem do PDF gerado por rdo_pdf_service.py."""
from datetime import datetime

from src.services.progress_service import SiteProgressResult
from src.services.xlsx_utils import (
    AMBER, BLUE, GRAY_200, GREEN, NAVY, RED, WHITE,
    new_workbook, write_footer, write_kpis, write_kv_rows, write_section, write_table, write_title,
)

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

MARCO_LEGEND = "Legenda MARCO: 0 = nao iniciado | 1 = preparacao/escavacao | 2 = estrutura/forma | 3 = execucao principal | 4 = concluido/liberado"


def _bool_label(val) -> str:
    if val is True or val == "true":
        return "Sim"
    if val is False or val == "false":
        return "Nao"
    return "-"


def _pct(value: float) -> float:
    """Retorna a fracao (0..1) pronta para number_format de percentual do Excel."""
    return round(value or 0.0, 4)


def _apply_pct_format(ws, row: int, col: int) -> None:
    ws.cell(row=row, column=col).number_format = "0.0%"


def _write_progress_sections(
    ws, row: int,
    project_progress: list[SiteProgressResult],
    current_site_id: int | None,
    until_label: str, advance_label: str,
    start_col_label: str, end_col_label: str,
    summary_title: str, detail_title_prefix: str,
) -> int:
    if not project_progress:
        return row

    row = write_section(ws, row, summary_title)
    header_row = row
    rows = [
        [sp.site_name, sp.profile_name or "-", _pct(sp.progress_yesterday), _pct(sp.day_advance), _pct(sp.progress_today)]
        for sp in project_progress
    ]
    row = write_table(
        ws, row, ["Site", "Perfil", until_label, advance_label, "Progresso Acumulado"],
        rows, col_widths=[26, 22, 18, 18, 20],
    )
    for r in range(header_row + 1, row - 1):
        for c in (3, 4, 5):
            _apply_pct_format(ws, r, c)

    current = next((sp for sp in project_progress if sp.site_id == current_site_id), None)
    if current and current.activities:
        row = write_section(ws, row, f"{detail_title_prefix} {current.site_name}")
        header_row = row
        rows = [
            [
                a.category_name, a.activity_name, a.unit or "-", a.total_qty,
                a.qty_yesterday, a.qty_today, _pct(a.pct_yesterday), _pct(a.pct_today),
                _pct(a.day_advance), a.marco if a.marco is not None else "-",
            ]
            for a in current.activities
        ]
        row = write_table(
            ws, row,
            ["Categoria", "Atividade", "Un.", "Qtd.", start_col_label, end_col_label, "% Ant.", "% Atu.", "Avanco", "Marco"],
            rows, col_widths=[20, 40, 8, 10, 12, 12, 10, 10, 10, 8],
        )
        for r in range(header_row + 1, row - 1):
            for c in (7, 8, 9):
                _apply_pct_format(ws, r, c)
        row = write_footer(ws, row, MARCO_LEGEND)
        row += 1
    return row


def generate_rdo_xlsx(
    report: dict,
    site_name: str = "",
    project_progress: list[SiteProgressResult] | None = None,
) -> bytes:
    """Gera o .xlsx do RDO diario e retorna os bytes."""
    site_name = site_name or report.get("local_site") or f"Site {report.get('site_id', '')}"
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    wb, ws = new_workbook(f"RDO {report.get('report_number', '')}")
    row = write_title(
        ws, 1, "RELATORIO DIARIO DE OBRA CIVIL",
        f"RDO no {report.get('report_number', '')}  |  {site_name}  |  {report.get('date', '')}",
    )

    # ── 1.1 Identificação ────────────────────────────────────────────────────
    row = write_section(ws, row, "1.1 Identificacao")
    row = write_kv_rows(ws, row, [
        ("Provincia", report.get("province")),
        ("Local / Site", report.get("local_site")),
        ("Responsavel de Obra", report.get("responsible")),
    ])
    row = write_kv_rows(ws, row, [
        ("Empreiteiro / Equipa", report.get("contractor")),
        ("Fiscal / Supervisor", report.get("supervisor")),
        ("Condicoes Climaticas", report.get("weather_conditions")),
    ])
    row = write_kv_rows(ws, row, [
        ("Situacao Geral", report.get("general_situation")),
        ("Hora Inicio", report.get("start_time")),
        ("Hora Termino", report.get("end_time")),
    ])

    # ── 1.2 Resumo do Dia ────────────────────────────────────────────────────
    row = write_section(ws, row, "1.2 Resumo do Dia")
    restrictions = report.get("restrictions_count") or 0
    row = write_kpis(ws, row, [
        ("Frentes Ativas", report.get("active_fronts") or 0, NAVY),
        ("Ativ. Concluidas", report.get("activities_completed") or 0, GREEN),
        ("Ativ. em Curso", report.get("activities_in_progress") or 0, BLUE),
        ("Restricoes", restrictions, AMBER if restrictions > 0 else GRAY_200),
        ("Total Pessoal", report.get("total_personnel") or 0, NAVY),
    ])
    row = write_kv_rows(ws, row, [
        ("Seg. / Saude", report.get("safety_situation")),
        ("Qualidade", report.get("quality_situation")),
        ("Comentario do Dia", report.get("short_comment")),
    ])

    # ── 1.3 Recursos Mobilizados ─────────────────────────────────────────────
    resources = [r for r in (report.get("resources") or []) if r.get("quantity", 0) > 0]
    if resources:
        row = write_section(ws, row, "1.3 Recursos Mobilizados")
        rows = [[r.get("discipline") or "", r.get("quantity") or 0, r.get("observations") or ""] for r in resources]
        rows.append(["TOTAL", sum(r.get("quantity") or 0 for r in resources), ""])
        row = write_table(ws, row, ["Disciplina", "Quantidade", "Observacoes"], rows, col_widths=[30, 14, 40])

    # ── 1.4 Atividades ───────────────────────────────────────────────────────
    activities = report.get("activities") or []
    if activities:
        row = write_section(ws, row, "1.4 Atividades Civis Executadas")
        rows = [
            [a.get("front_site") or "", a.get("civil_category") or "", a.get("activity_description") or "",
             a.get("unit") or "", a.get("qty_day"), a.get("status") or ""]
            for a in activities
        ]
        row = write_table(ws, row, ["Frente", "Categoria", "Atividade", "Un.", "Qtd.", "Status"], rows,
                           col_widths=[16, 18, 34, 8, 10, 16])

    # ── 1.5 Materiais ────────────────────────────────────────────────────────
    materials = report.get("materials") or []
    if materials:
        row = write_section(ws, row, "1.5 Materiais Recebidos / Aplicados")
        rows = [
            [m.get("material_name") or "", m.get("unit") or "", m.get("qty_received") or 0,
             m.get("qty_applied") or 0, m.get("balance") or 0, m.get("observations") or ""]
            for m in materials
        ]
        row = write_table(
            ws, row, ["Material / Equipamento", "Un.", "Qtd. Recebida", "Qtd. Aplicada", "Saldo", "Obs."],
            rows, col_widths=[30, 8, 14, 14, 10, 24],
        )

    # ── 1.6 Ocorrências ──────────────────────────────────────────────────────
    occurrences = report.get("occurrences") or []
    if occurrences:
        row = write_section(ws, row, "1.6 Ocorrencias, Impedimentos e Riscos")
        rows = [
            [o.get("occurrence_type") or "", o.get("description") or "", o.get("impact") or "",
             o.get("corrective_action") or "", o.get("responsible") or ""]
            for o in occurrences
        ]
        row = write_table(ws, row, ["Tipo", "Descricao", "Impacto", "Acao Corretiva", "Resp."], rows,
                           col_widths=[14, 34, 12, 28, 18])

    # ── 1.7 Qualidade / Segurança ────────────────────────────────────────────
    quality_checks = report.get("quality_checks") or []
    if quality_checks:
        row = write_section(ws, row, "1.7 Qualidade, Seguranca e Conformidade")
        rows = [
            [QUALITY_LABELS.get(q.get("check_type") or "", q.get("check_type") or ""),
             _bool_label(q.get("result")), q.get("observations") or ""]
            for q in quality_checks
        ]
        row = write_table(ws, row, ["Item de Verificacao", "Resultado", "Observacoes"], rows,
                           col_widths=[40, 12, 30])

    # ── 1.9 Planeamento D+1 ──────────────────────────────────────────────────
    plans = report.get("next_day_plans") or []
    if plans:
        row = write_section(ws, row, "1.9 Planeamento para o Dia Seguinte")
        rows = [
            [p.get("front_site") or "", p.get("planned_activity") or "", p.get("responsible") or "", p.get("dependency") or ""]
            for p in plans
        ]
        row = write_table(ws, row, ["Frente/Site", "Atividade Prevista", "Responsavel", "Dependencia"], rows,
                           col_widths=[18, 34, 18, 18])

    # ── 1.10 Conclusão ───────────────────────────────────────────────────────
    if report.get("daily_conclusion"):
        row = write_section(ws, row, "1.10 Conclusao Diaria do Responsavel")
        row = write_kv_rows(ws, row, [("Conclusao", report["daily_conclusion"])], n_per_row=1)

    # ── 1.11 Assinaturas ─────────────────────────────────────────────────────
    signatures = report.get("signatures") or []
    sig_with_data = [s for s in signatures if s.get("name")]
    if sig_with_data:
        row = write_section(ws, row, "1.11 Assinaturas")
        rows = []
        for s in sig_with_data:
            confirmed = ""
            if s.get("confirmed_at"):
                try:
                    confirmed = datetime.fromisoformat(s["confirmed_at"]).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    confirmed = s["confirmed_at"]
            rows.append([SIG_LABELS.get(s.get("role") or "", s.get("role") or ""), s.get("name") or "", confirmed])
        row = write_table(ws, row, ["Funcao", "Nome", "Data/Hora Confirmacao"], rows, col_widths=[24, 30, 20])

    # ── 1.12 / 1.13 Progresso de Obra (EVM) ──────────────────────────────────
    row = _write_progress_sections(
        ws, row, project_progress or [], report.get("site_id"),
        until_label="Progresso Ate Ontem", advance_label="Avanco do Dia",
        start_col_label="Ontem", end_col_label="Hoje",
        summary_title="1.12 Resumo de Progresso por Site (Projeto)",
        detail_title_prefix="1.13 Medicao Objetiva de Progresso -",
    )

    write_footer(ws, row, f"Documento gerado automaticamente em {generated_at} | U2 Broadcast")

    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_weekly_rdo_xlsx(
    reports: list[dict],
    site_name: str,
    week_label: str,
    project_progress: list[SiteProgressResult] | None = None,
) -> bytes:
    """Gera o .xlsx do RDO semanal consolidado e retorna os bytes."""
    from datetime import date as _date

    def _fmt_date(iso: str, fmt: str = "%d/%m/%Y") -> str:
        try:
            return _date.fromisoformat(iso).strftime(fmt)
        except Exception:
            return iso

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    total_personnel = sum(r.get("total_personnel") or 0 for r in reports)
    total_acts_completed = sum(r.get("activities_completed") or 0 for r in reports)
    total_occurrences = sum(len(r.get("occurrences") or []) for r in reports)

    wb, ws = new_workbook(f"Semanal {week_label}")
    row = write_title(ws, 1, "RELATORIO SEMANAL DE OBRA CIVIL", f"{site_name}  |  Semana: {week_label}")

    # ── Resumo da Semana ─────────────────────────────────────────────────────
    row = write_section(ws, row, "Resumo da Semana")
    rows = [
        [_fmt_date(r.get("date", "")), r.get("report_number", "-"), r.get("active_fronts") or 0,
         r.get("total_personnel") or 0, r.get("activities_completed") or 0, r.get("activities_in_progress") or 0,
         r.get("restrictions_count") or 0, r.get("general_situation") or "-"]
        for r in reports
    ]
    rows.append(["TOTAL SEMANA", "-", "-", total_personnel, total_acts_completed, "-", "-", "-"])
    row = write_table(
        ws, row,
        ["Data", "RDO#", "Frentes", "Pessoal", "Ativ. Concl.", "Ativ. Curso", "Restricoes", "Situacao"],
        rows, col_widths=[12, 8, 10, 10, 12, 12, 12, 14],
    )

    row = write_kpis(ws, row, [
        ("RDOs no Periodo", len(reports), NAVY),
        ("Total Pessoal", total_personnel, BLUE),
        ("Ativ. Concluidas", total_acts_completed, GREEN),
        ("Ocorrencias", total_occurrences, RED if total_occurrences > 0 else GRAY_200),
    ])

    # ── Atividades Executadas na Semana ──────────────────────────────────────
    all_activities = [(_fmt_date(r.get("date", ""), "%d/%m"), a) for r in reports for a in (r.get("activities") or [])]
    if all_activities:
        row = write_section(ws, row, "Atividades Executadas na Semana")
        rows = [
            [date_fmt, a.get("front_site") or "", a.get("civil_category") or "", a.get("activity_description") or "",
             a.get("unit") or "", a.get("qty_day"), a.get("status") or ""]
            for date_fmt, a in all_activities
        ]
        row = write_table(ws, row, ["Data", "Frente", "Categoria", "Atividade", "Un.", "Qtd.", "Status"], rows,
                           col_widths=[10, 16, 18, 34, 8, 10, 16])

    # ── Ocorrências da Semana ────────────────────────────────────────────────
    all_occurrences = [(_fmt_date(r.get("date", ""), "%d/%m"), o) for r in reports for o in (r.get("occurrences") or [])]
    if all_occurrences:
        row = write_section(ws, row, "Ocorrencias e Impedimentos da Semana")
        rows = [
            [date_fmt, o.get("occurrence_type") or "", o.get("description") or "", o.get("impact") or "", o.get("responsible") or ""]
            for date_fmt, o in all_occurrences
        ]
        row = write_table(ws, row, ["Data", "Tipo", "Descricao", "Impacto", "Responsavel"], rows,
                           col_widths=[10, 14, 34, 12, 18])

    # ── Planeamento — último dia da semana ───────────────────────────────────
    last_plans = (reports[-1].get("next_day_plans") or []) if reports else []
    if last_plans:
        row = write_section(ws, row, "Planeamento - Proximo Periodo")
        rows = [
            [p.get("front_site") or "", p.get("planned_activity") or "", p.get("responsible") or "", p.get("dependency") or ""]
            for p in last_plans
        ]
        row = write_table(ws, row, ["Frente/Site", "Atividade Prevista", "Responsavel", "Dependencia"], rows,
                           col_widths=[18, 34, 18, 18])

    # ── Progresso de Obra (EVM) ───────────────────────────────────────────────
    current_site_id = reports[0].get("site_id") if reports else None
    row = _write_progress_sections(
        ws, row, project_progress or [], current_site_id,
        until_label="Ate Inicio da Semana", advance_label="Avanco da Semana",
        start_col_label="Ini. Sem.", end_col_label="Fim Sem.",
        summary_title="Resumo de Progresso por Site (Projeto)",
        detail_title_prefix="Medicao Objetiva de Progresso -",
    )

    write_footer(ws, row, f"Documento gerado automaticamente em {generated_at} | U2 Broadcast")

    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
