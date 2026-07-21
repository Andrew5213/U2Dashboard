"""Geração de .xlsx para os relatórios ClickUp (Executivo, Província, Diário/Semanal),
espelhando as mesmas seções e dados já montados por report_service.py::_build_data.
Cada render_* recebe o MESMO dict retornado por _build_data — nenhuma lógica de
busca de dados é duplicada aqui, só a escrita em planilha."""
from io import BytesIO

from src.services.xlsx_utils import (
    AMBER, BLUE, GRAY_200, GREEN, NAVY, RED,
    new_workbook, write_footer, write_kpis, write_kv_rows, write_section, write_table, write_title,
)


def _to_bytes(wb) -> bytes:
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _apply_pct_col(ws, first_row: int, last_row: int, col: int) -> None:
    for r in range(first_row, last_row):
        ws.cell(row=r, column=col).number_format = "0.0%"


# ── Executivo (ReportService) ──────────────────────────────────────────────────

def render_executive_xlsx(data: dict) -> bytes:
    wb, ws = new_workbook(data["space_name"])
    row = write_title(ws, 1, "RELATORIO EXECUTIVO", data["space_name"])

    kpis = data["kpis"]
    row = write_section(ws, row, "Visao Geral")
    row = write_kpis(ws, row, [
        ("Total de Tasks", kpis["total_tasks"], NAVY),
        ("Concluidas", kpis["completed_tasks"], GREEN),
        ("Em Atraso", kpis["overdue_tasks"], RED if kpis["overdue_tasks"] else GRAY_200),
        ("Pastas", kpis["total_folders"], BLUE),
        ("Listas", kpis["total_lists"], BLUE),
    ])
    row = write_kv_rows(ws, row, [("Taxa de Conclusao", kpis["completion_rate"])])
    ws.cell(row=row - 2, column=2).number_format = "0.0%"

    if kpis.get("status_distribution"):
        row = write_section(ws, row, "Distribuicao por Status")
        rows = sorted(kpis["status_distribution"].items(), key=lambda kv: -kv[1])
        row = write_table(ws, row, ["Status", "Qtd."], [[k, v] for k, v in rows], col_widths=[24, 10])

    all_lists = list(data.get("folders") or []) + ([{"name": "(Sem Pasta)", "lists": data["folderless_lists"]}] if data.get("folderless_lists") else [])
    if all_lists:
        row = write_section(ws, row, "Pastas / Provincias")
        header_row = row
        rows = [
            [f["name"], f.get("total_lists", len(f.get("lists", []))), f.get("total_tasks", 0),
             f.get("completed_tasks", 0), f.get("overdue_tasks", 0), f.get("completion_rate", 0)]
            for f in all_lists
        ]
        row = write_table(ws, row, ["Pasta", "Listas", "Total Tasks", "Concluidas", "Atrasadas", "% Conclusao"], rows,
                           col_widths=[26, 10, 12, 12, 12, 12])
        _apply_pct_col(ws, header_row + 1, row - 1, 6)

        for f in all_lists:
            if not f.get("lists"):
                continue
            row = write_section(ws, row, f"Listas - {f['name']}")
            header_row = row
            rows = [[l["name"], l.get("total_tasks", 0), l.get("completed_tasks", 0), l.get("overdue_tasks", 0), l.get("completion_rate", 0)] for l in f["lists"]]
            row = write_table(ws, row, ["Lista", "Total Tasks", "Concluidas", "Atrasadas", "% Conclusao"], rows,
                               col_widths=[26, 12, 12, 12, 12])
            _apply_pct_col(ws, header_row + 1, row - 1, 5)

    if data.get("overdue_tasks"):
        row = write_section(ws, row, "Tasks em Atraso")
        rows = [[t["name"], t.get("folder_name", ""), t.get("list_name", ""), t.get("due_date_fmt", ""), t.get("assignees_str", "")] for t in data["overdue_tasks"]]
        row = write_table(ws, row, ["Task", "Pasta", "Lista", "Vencimento", "Responsaveis"], rows,
                           col_widths=[34, 18, 18, 12, 24])

    if data.get("upcoming_tasks"):
        row = write_section(ws, row, "Proximas Tasks")
        rows = [[t["name"], t.get("folder_name", ""), t.get("list_name", ""), t.get("due_date_fmt", ""), t.get("assignees_str", "")] for t in data["upcoming_tasks"]]
        row = write_table(ws, row, ["Task", "Pasta", "Lista", "Vencimento", "Responsaveis"], rows,
                           col_widths=[34, 18, 18, 12, 24])

    if data.get("assignee_stats"):
        row = write_section(ws, row, "Desempenho da Equipa")
        rows = [[a["assignee"], a["open"], a["completed"], a["overdue"], a["total"], a["completion_rate"]] for a in data["assignee_stats"]]
        header_row = row
        row = write_table(ws, row, ["Responsavel", "Em Aberto", "Concluidas", "Atrasadas", "Total", "% Conclusao"], rows,
                           col_widths=[24, 12, 12, 12, 10, 12])
        _apply_pct_col(ws, header_row + 1, row - 1, 6)

    write_footer(ws, row, f"Documento gerado automaticamente em {data['generated_at']}")
    return _to_bytes(wb)


# ── Provincia (ProvinceReportService) ──────────────────────────────────────────

def render_province_xlsx(data: dict) -> bytes:
    wb, ws = new_workbook(data["folder_name"])
    row = write_title(ws, 1, "RELATORIO DE PROVINCIA", f"{data['folder_name']}  |  {data['space_name']}")

    kpis = data["kpis"]
    row = write_section(ws, row, "Visao Geral")
    row = write_kpis(ws, row, [
        ("Total de Tasks", kpis["total_tasks"], NAVY),
        ("Concluidas", kpis["completed_tasks"], GREEN),
        ("Em Atraso", kpis["overdue_tasks"], RED if kpis["overdue_tasks"] else GRAY_200),
        ("Listas (Modulos)", data["total_lists"], BLUE),
    ])
    kv = [("Taxa de Conclusao (simples)", kpis["completion_rate"])]
    if data.get("weighted_progress_pct") is not None:
        kv.append(("Progresso Ponderado (EVM)", data["weighted_progress"]))
    row = write_kv_rows(ws, row, kv)
    for c in range(1, len(kv) + 1):
        ws.cell(row=row - 2, column=c).number_format = "0.0%"

    if data.get("lists"):
        row = write_section(ws, row, "Modulos (Listas)")
        header_row = row
        rows = [
            [l["name"], l.get("weight_pct", "-"), l.get("total_tasks", 0), l.get("completed_tasks", 0),
             l.get("overdue_tasks", 0), l.get("completion_rate", 0)]
            for l in data["lists"]
        ]
        row = write_table(ws, row, ["Modulo", "Peso", "Total Tasks", "Concluidas", "Atrasadas", "% Progresso"], rows,
                           col_widths=[24, 10, 12, 12, 12, 12])
        _apply_pct_col(ws, header_row + 1, row - 1, 6)

    for lst in data.get("lists_detail") or []:
        tasks = lst.get("tasks") or []
        if not tasks:
            continue
        row = write_section(ws, row, f"Detalhe - {lst['name']}")
        rows = [
            [tk["name"], tk.get("status", ""), tk.get("assignees_str", ""), tk.get("due_date_fmt", ""),
             "Sub-tarefa" if tk.get("parent_task_id") else "Disciplina"]
            for tk in tasks
        ]
        row = write_table(ws, row, ["Disciplina / Atividade", "Status", "Responsaveis", "Vencimento", "Nivel"], rows,
                           col_widths=[34, 16, 22, 12, 12])

    if data.get("overdue_tasks"):
        row = write_section(ws, row, "Tasks em Atraso")
        rows = [[t["name"], t.get("list_name", ""), t.get("due_date_fmt", ""), t.get("assignees_str", "")] for t in data["overdue_tasks"]]
        row = write_table(ws, row, ["Task", "Modulo", "Vencimento", "Responsaveis"], rows, col_widths=[34, 20, 12, 24])

    if data.get("upcoming_tasks"):
        row = write_section(ws, row, "Proximas Tasks")
        rows = [
            [t.get("name", ""), t.get("list_name", ""), t.get("due_date_fmt") or t.get("due_date", ""), t.get("assignees_str", "")]
            for t in data["upcoming_tasks"]
        ]
        row = write_table(ws, row, ["Task", "Modulo", "Vencimento", "Responsaveis"], rows, col_widths=[34, 20, 12, 24])

    if data.get("assignee_stats"):
        row = write_section(ws, row, "Desempenho da Equipa")
        rows = [[a["assignee"], a["open"], a["completed"], a["overdue"], a["total"], a["completion_rate"]] for a in data["assignee_stats"]]
        header_row = row
        row = write_table(ws, row, ["Responsavel", "Em Aberto", "Concluidas", "Atrasadas", "Total", "% Conclusao"], rows,
                           col_widths=[24, 12, 12, 12, 10, 12])
        _apply_pct_col(ws, header_row + 1, row - 1, 6)

    write_footer(ws, row, f"Documento gerado automaticamente em {data['generated_at']}")
    return _to_bytes(wb)


# ── Periódico (Diário / Semanal) ────────────────────────────────────────────────

def render_periodic_xlsx(data: dict) -> bytes:
    wb, ws = new_workbook(data["report_type"])
    row = write_title(ws, 1, data["report_type"].upper(), f"{data['space_name']}  |  {data['period_label']}")

    row = write_section(ws, row, "Resumo do Periodo")
    row = write_kpis(ws, row, [
        ("Provincias com Atividade", data["n_provinces"], NAVY),
        ("Concluidas", data["n_concluded"], GREEN),
        ("Atualizadas", data["n_updated"], AMBER),
    ])

    def _write_tasks_block(title: str, tasks: list[dict]) -> None:
        nonlocal row
        if not tasks:
            return
        row = write_section(ws, row, title)
        rows = []
        for tk in tasks:
            rows.append([tk.get("name", ""), tk.get("status", ""), tk.get("list_name", ""), tk.get("assignees_str", ""), tk.get("date_ref")])
            for sub in tk.get("subtasks") or []:
                rows.append([f"  ↳ {sub.get('name', '')}", sub.get("status", ""), sub.get("list_name", ""), sub.get("assignees_str", ""), sub.get("date_ref")])
        header_row = row
        row = write_table(ws, row, ["Tarefa", "Status", "Lista", "Responsaveis", "Data"], rows,
                           col_widths=[34, 16, 18, 22, 18])
        for r in range(header_row + 1, row - 1):
            c = ws.cell(row=r, column=5)
            if c.value is not None:
                c.number_format = "dd/mm/yyyy hh:mm"

    if data.get("folders"):
        for folder in data["folders"]:
            categories = {"concluded": [], "updated": []}
            for tk in folder["tasks"]:
                categories.setdefault(tk["category"], []).append(tk)
            labels = {"concluded": "Concluidas", "updated": "Atualizadas"}
            for cat, label in labels.items():
                _write_tasks_block(f"{folder['folder_name']} - {label}", categories.get(cat, []))
    else:
        row = write_section(ws, row, "Sem atualizacoes no periodo")

    write_footer(ws, row, f"Documento gerado automaticamente em {data['generated_at']}")
    return _to_bytes(wb)
