"""
Strings traduzidas para geração de relatórios PDF.
Suporte: 'pt' (Português) e 'en' (English).
"""

STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        # ── Footer / Header ───────────────────────────────────────────────────
        "footer_report_title": "Relatorio de Projetos",
        "footer_page": "Pagina",
        "footer_of": "de",
        "utc_label": "(UTC)",
        "at_time": " as ",
        # ── Capa executiva ────────────────────────────────────────────────────
        "cover_eyebrow": "U2 BROADCAST",
        "cover_title": "Relatorio de\nGestao de Projetos",
        "cover_kpi_total": "TAREFAS TOTAIS",
        "cover_kpi_rate": "TAXA DE CONCLUSAO",
        "cover_kpi_overdue": "EM ATRASO",
        "cover_meta_generated": "DATA DE GERACAO",
        "cover_meta_updated": "ULTIMA ATUALIZACAO DOS DADOS",
        "cover_meta_folders_lists": "PASTAS: {f}   ·   LISTAS: {l}",
        "cover_footnote": (
            "Documento gerado automaticamente pelo sistema de gestao de projetos U2 Broadcast.\n"
            "Os dados refletem o estado do cache local conforme a ultima sincronizacao indicada acima."
        ),
        # ── Resumo Executivo ──────────────────────────────────────────────────
        "exec_section": "Resumo Executivo",
        "exec_subtitle": "Visao consolidada de todos os projetos e tarefas - {space}",
        "card_total": "Total de Tarefas",
        "card_completed": "Concluidas",
        "card_overdue": "Em Atraso",
        "card_no_due": "Sem Prazo",
        "card_sub_folders_lists": "{f} pastas · {l} listas",
        "card_sub_of_total": "do total",
        "card_sub_overdue_tasks": "tarefas vencidas",
        "card_sub_no_date": "sem data definida",
        "status_dist_label": "DISTRIBUICAO POR STATUS",
        "top_areas_section": "Top Areas por Atividade",
        "top_areas_subtitle": "Pastas ordenadas por volume de tarefas e suas taxas de conclusao",
        "task_count_suffix": "tar.",
        "alerts_section": "Alertas Executivos",
        "alerts_subtitle": "Pontos de atencao identificados automaticamente a partir dos dados",
        "alert_overdue": "{n} tarefa(s) com prazo vencido ainda em aberto - requer atencao imediata.",
        "alert_no_due": "{n} tarefas ({pct}%) sem prazo definido dificultam o planejamento.",
        "alert_low_rate": "Taxa de conclusao de {pct} indica baixo progresso geral nos projetos.",
        "alert_mid_rate": "Taxa de conclusao de {pct} esta abaixo do ideal (40%).",
        "alert_ok_rate": "Taxa de conclusao de {pct} esta dentro do esperado.",
        "alert_top_area": "Area '{name}' concentra o maior numero de atrasos ({n} tarefa(s)).",
        "alert_no_issues": "Nenhum ponto critico identificado nos dados atuais.",
        # ── Saúde dos projetos ────────────────────────────────────────────────
        "health_section": "Saude dos Projetos por Area",
        "health_subtitle": "Metricas de conclusao e tarefas em atraso agrupadas por pasta e lista",
        "col_project_list": "Projeto / Lista",
        "col_tasks": "Tarefas",
        "col_completed_hdr": "Concluidas",
        "col_overdue_hdr": "Em Atraso",
        "col_completion_rate": "Taxa de Conclusao",
        "no_projects": "Nenhum projeto encontrado. Execute uma atualizacao de cache.",
        # ── Tarefas em Atraso ─────────────────────────────────────────────────
        "overdue_section": "Tarefas em Atraso ({n})",
        "overdue_subtitle": "Tarefas com prazo vencido ainda pendentes de conclusao, por data de vencimento",
        "col_task": "Tarefa",
        "col_list_project": "Lista / Projeto",
        "col_assignee": "Responsavel",
        "col_due_date": "Vencimento",
        "col_delay": "Atraso",
        "day_singular": "dia",
        "day_plural": "dias",
        # ── Próximas Entregas ─────────────────────────────────────────────────
        "upcoming_section": "Proximas Entregas - 30 dias ({n})",
        "upcoming_subtitle": "Tarefas abertas com vencimento nos proximos 30 dias, em ordem cronologica",
        "col_area": "Area",
        # ── Equipe ────────────────────────────────────────────────────────────
        "team_section": "Desempenho da Equipe",
        "team_subtitle": "Tarefas em aberto, concluidas e em atraso por responsavel",
        "col_open": "Em Aberto",
        # ── Capa Província ────────────────────────────────────────────────────
        "prov_cover_eyebrow": "U2 BROADCAST  ·  RELATORIO DE PROVINCIA",
        "prov_cover_title": "Relatorio Detalhado\nde Provincia",
        "prov_kpi_total": "TAREFAS TOTAIS",
        "prov_kpi_simple": "TAXA SIMPLES",
        "prov_kpi_weighted": "PROG. PONDERADO",
        "prov_kpi_overdue": "EM ATRASO",
        "prov_meta_lists": "LISTAS",
        "prov_meta_generated": "DATA DE GERACAO",
        "prov_meta_updated": "ULTIMA ATUALIZACAO",
        "prov_footnote": (
            "Documento gerado automaticamente pelo sistema de gestao de projetos U2 Broadcast.\n"
            "Os dados refletem o estado do cache local conforme a ultima sincronizacao indicada acima."
        ),
        # ── Resumo Província ──────────────────────────────────────────────────
        "prov_section": "Resumo - {name}",
        "prov_subtitle": "Visao consolidada das listas e tarefas da provincia - {space}",
        "card_lists_count": "{n} lista(s)",
        "weighted_section": "Progresso Ponderado por Disciplina",
        "weighted_subtitle": "Avanco fisico calculado pelo peso de cada disciplina (EVM - Earned Value Method)",
        "weighted_global_label": "PROGRESSO FISICO GLOBAL PONDERADO",
        "disc_cols_discipline": "Disciplina",
        "disc_cols_weight": "Peso",
        "disc_cols_progress": "Progresso",
        "disc_cols_contribution": "Contribuicao",
        "disc_cols_tasks": "Tarefas",
        "disc_cols_rate": "Taxa",
        "list_summary_section": "Resumo por Lista / Disciplina",
        "list_summary_subtitle": "Metricas de conclusao e atrasos por disciplina desta provincia",
        "list_summary_cont": "Resumo por Lista / Disciplina (cont.)",
        "col_list": "Lista",
        "col_weight": "Peso",
        "col_rate": "Taxa Conclusao",
        # ── Bloco pesos disciplinas ───────────────────────────────────────────
        "disc_block_title": "PESOS POR DISCIPLINA  (progresso ponderado por engenharia)",
        "disc_hdr_discipline": "DISCIPLINA",
        "disc_hdr_rel_weight": "PESO REL.",
        "disc_hdr_weight_pct": "PESO %",
        "disc_hdr_progress": "AVANCO %",
        "disc_hdr_contrib": "CONTRIB.",
        # ── Detalhe por Lista ─────────────────────────────────────────────────
        "list_section": "Lista: {name}",
        "list_detail_subtitle": "{n} tarefa(s) · {c} concluida(s) · {o} em atraso · Prog. Pond.: {p}",
        "list_cont": "Lista: {name} (cont.)",
        "no_tasks": "Nenhuma tarefa encontrada nesta lista.",
        "col_peso": "Peso",
        "col_status": "Status",
        # ── Rodapé ────────────────────────────────────────────────────────────
        "footnote": (
            "Relatorio gerado automaticamente pelo sistema de gestao de projetos U2 Broadcast em {date}. "
            "Os dados refletem o estado do cache local atualizado em {refresh}. "
            "Para dados em tempo real, acesse o dashboard ou force uma atualizacao via POST /dashboard/refresh."
        ),
        # ── Dados dinâmicos ───────────────────────────────────────────────────
        "no_date": "Sem prazo",
        "na": "N/D",
        # ── Relatório Periódico ───────────────────────────────────────────────
        "periodic_footer": "Relatorio {type} de Atualizacoes",
        "periodic_cover_title": "Relatorio {type}\nde Atualizacoes",
        "periodic_kpi_provinces": "PROVINCIAS COM UPDATES",
        "periodic_kpi_concluded": "TAREFAS CONCLUIDAS",
        "periodic_kpi_created": "NOVAS TAREFAS",
        "periodic_kpi_updated": "ATUALIZACOES",
        "periodic_meta_generated": "DATA DE GERACAO",
        "periodic_meta_updated": "ULTIMA ATUALIZACAO DOS DADOS",
        "periodic_meta_space": "ESPACO",
        "periodic_footnote": (
            "Documento gerado automaticamente pelo sistema de gestao de projetos U2 Broadcast.\n"
            "Este relatorio apresenta apenas tarefas com atividade no periodo indicado acima."
        ),
        "prov_updates_section": "Provincia: {name}",
        "prov_updates_cont": "Provincia: {name} (cont.)",
        "prov_updates_subtitle": "Periodo: {period}  ·  {concluded} concluidas · {created} criadas · {updated} atualizadas",
        "prov_updates_subs_suffix": "  · {n} subtarefa(s)",
        "cat_concluded": "Concluidas no periodo ({n})",
        "cat_created": "Criadas no periodo ({n})",
        "cat_updated": "Atualizadas no periodo ({n})",
        "list_info_tasks": "{n} tarefa(s)",
        "list_info_subs": "  ·  {n} subtarefa(s)",
        "no_updates_section": "Sem Atualizacoes",
        "no_updates_subtitle": "Nenhuma tarefa foi alterada no periodo: {period}",
        "no_updates_body": "Nenhuma atividade registrada no periodo.",
        # ── Tipos periódicos ──────────────────────────────────────────────────
        "daily_type": "Diario",
        "daily_period": "Dia {date}",
        "weekly_type": "Semanal",
        "weekly_period": "Semana de {start} a {end}",
        # ── Nomes de arquivo ──────────────────────────────────────────────────
        "filename_executive": "relatorio_executivo_{ts}.pdf",
        "filename_province": "relatorio_provincia_{folder_id}_{ts}.pdf",
        "filename_daily": "relatorio_diario_{ts}.pdf",
        "filename_weekly": "relatorio_semanal_{ts}.pdf",
    },
    "en": {
        # ── Footer / Header ───────────────────────────────────────────────────
        "footer_report_title": "Project Report",
        "footer_page": "Page",
        "footer_of": "of",
        "utc_label": "(UTC)",
        "at_time": " at ",
        # ── Executive cover ───────────────────────────────────────────────────
        "cover_eyebrow": "U2 BROADCAST",
        "cover_title": "Project\nManagement Report",
        "cover_kpi_total": "TOTAL TASKS",
        "cover_kpi_rate": "COMPLETION RATE",
        "cover_kpi_overdue": "OVERDUE",
        "cover_meta_generated": "GENERATED ON",
        "cover_meta_updated": "LAST DATA UPDATE",
        "cover_meta_folders_lists": "FOLDERS: {f}   ·   LISTS: {l}",
        "cover_footnote": (
            "This document was automatically generated by the U2 Broadcast project management system.\n"
            "Data reflects the local cache state as of the last sync indicated above."
        ),
        # ── Executive Summary ─────────────────────────────────────────────────
        "exec_section": "Executive Summary",
        "exec_subtitle": "Consolidated view of all projects and tasks - {space}",
        "card_total": "Total Tasks",
        "card_completed": "Completed",
        "card_overdue": "Overdue",
        "card_no_due": "No Due Date",
        "card_sub_folders_lists": "{f} folders · {l} lists",
        "card_sub_of_total": "of total",
        "card_sub_overdue_tasks": "overdue tasks",
        "card_sub_no_date": "no date set",
        "status_dist_label": "STATUS DISTRIBUTION",
        "top_areas_section": "Top Areas by Activity",
        "top_areas_subtitle": "Folders sorted by task volume and their completion rates",
        "task_count_suffix": "tasks",
        "alerts_section": "Executive Alerts",
        "alerts_subtitle": "Attention points automatically identified from the data",
        "alert_overdue": "{n} task(s) with overdue deadline still open - requires immediate attention.",
        "alert_no_due": "{n} tasks ({pct}%) without a set deadline hinder planning.",
        "alert_low_rate": "Completion rate of {pct} indicates low overall project progress.",
        "alert_mid_rate": "Completion rate of {pct} is below the ideal threshold (40%).",
        "alert_ok_rate": "Completion rate of {pct} is within the expected range.",
        "alert_top_area": "Area '{name}' has the highest number of delays ({n} task(s)).",
        "alert_no_issues": "No critical issues identified in the current data.",
        # ── Project Health ────────────────────────────────────────────────────
        "health_section": "Project Health by Area",
        "health_subtitle": "Completion metrics and overdue tasks grouped by folder and list",
        "col_project_list": "Project / List",
        "col_tasks": "Tasks",
        "col_completed_hdr": "Completed",
        "col_overdue_hdr": "Overdue",
        "col_completion_rate": "Completion Rate",
        "no_projects": "No projects found. Run a cache refresh.",
        # ── Overdue Tasks ─────────────────────────────────────────────────────
        "overdue_section": "Overdue Tasks ({n})",
        "overdue_subtitle": "Tasks with overdue deadlines still pending completion, by due date",
        "col_task": "Task",
        "col_list_project": "List / Project",
        "col_assignee": "Assignee",
        "col_due_date": "Due Date",
        "col_delay": "Delay",
        "day_singular": "day",
        "day_plural": "days",
        # ── Upcoming Deliveries ───────────────────────────────────────────────
        "upcoming_section": "Upcoming Deliveries - 30 days ({n})",
        "upcoming_subtitle": "Open tasks due within the next 30 days, in chronological order",
        "col_area": "Area",
        # ── Team ──────────────────────────────────────────────────────────────
        "team_section": "Team Performance",
        "team_subtitle": "Open, completed, and overdue tasks per assignee",
        "col_open": "Open",
        # ── Province Cover ────────────────────────────────────────────────────
        "prov_cover_eyebrow": "U2 BROADCAST  ·  PROVINCE REPORT",
        "prov_cover_title": "Detailed Province\nReport",
        "prov_kpi_total": "TOTAL TASKS",
        "prov_kpi_simple": "SIMPLE RATE",
        "prov_kpi_weighted": "WEIGHTED PROG.",
        "prov_kpi_overdue": "OVERDUE",
        "prov_meta_lists": "LISTS",
        "prov_meta_generated": "GENERATED ON",
        "prov_meta_updated": "LAST UPDATE",
        "prov_footnote": (
            "This document was automatically generated by the U2 Broadcast project management system.\n"
            "Data reflects the local cache state as of the last sync indicated above."
        ),
        # ── Province Summary ──────────────────────────────────────────────────
        "prov_section": "Summary - {name}",
        "prov_subtitle": "Consolidated view of the province lists and tasks - {space}",
        "card_lists_count": "{n} list(s)",
        "weighted_section": "Weighted Progress by Discipline",
        "weighted_subtitle": "Physical progress calculated by discipline weight (EVM - Earned Value Method)",
        "weighted_global_label": "GLOBAL WEIGHTED PHYSICAL PROGRESS",
        "disc_cols_discipline": "Discipline",
        "disc_cols_weight": "Weight",
        "disc_cols_progress": "Progress",
        "disc_cols_contribution": "Contribution",
        "disc_cols_tasks": "Tasks",
        "disc_cols_rate": "Rate",
        "list_summary_section": "Summary by List / Discipline",
        "list_summary_subtitle": "Completion and overdue metrics per discipline in this province",
        "list_summary_cont": "Summary by List / Discipline (cont.)",
        "col_list": "List",
        "col_weight": "Weight",
        "col_rate": "Completion Rate",
        # ── Discipline weights block ───────────────────────────────────────────
        "disc_block_title": "DISCIPLINE WEIGHTS  (engineering weighted progress)",
        "disc_hdr_discipline": "DISCIPLINE",
        "disc_hdr_rel_weight": "REL. WEIGHT",
        "disc_hdr_weight_pct": "WEIGHT %",
        "disc_hdr_progress": "PROGRESS %",
        "disc_hdr_contrib": "CONTRIB.",
        # ── List Detail ───────────────────────────────────────────────────────
        "list_section": "List: {name}",
        "list_detail_subtitle": "{n} task(s) · {c} completed · {o} overdue · Weighted Prog.: {p}",
        "list_cont": "List: {name} (cont.)",
        "no_tasks": "No tasks found in this list.",
        "col_peso": "Weight",
        "col_status": "Status",
        # ── Footnote ──────────────────────────────────────────────────────────
        "footnote": (
            "Report automatically generated by the U2 Broadcast project management system on {date}. "
            "Data reflects the local cache state last updated on {refresh}. "
            "For real-time data, access the dashboard or force a refresh via POST /dashboard/refresh."
        ),
        # ── Dynamic data strings ──────────────────────────────────────────────
        "no_date": "No due date",
        "na": "N/A",
        # ── Periodic Report ───────────────────────────────────────────────────
        "periodic_footer": "{type} Updates Report",
        "periodic_cover_title": "{type}\nUpdates Report",
        "periodic_kpi_provinces": "PROVINCES WITH UPDATES",
        "periodic_kpi_concluded": "COMPLETED TASKS",
        "periodic_kpi_created": "NEW TASKS",
        "periodic_kpi_updated": "UPDATES",
        "periodic_meta_generated": "GENERATED ON",
        "periodic_meta_updated": "LAST DATA UPDATE",
        "periodic_meta_space": "SPACE",
        "periodic_footnote": (
            "This document was automatically generated by the U2 Broadcast project management system.\n"
            "This report shows only tasks with activity in the indicated period."
        ),
        "prov_updates_section": "Province: {name}",
        "prov_updates_cont": "Province: {name} (cont.)",
        "prov_updates_subtitle": "Period: {period}  ·  {concluded} completed · {created} created · {updated} updated",
        "prov_updates_subs_suffix": "  · {n} subtask(s)",
        "cat_concluded": "Completed in period ({n})",
        "cat_created": "Created in period ({n})",
        "cat_updated": "Updated in period ({n})",
        "list_info_tasks": "{n} task(s)",
        "list_info_subs": "  ·  {n} subtask(s)",
        "no_updates_section": "No Updates",
        "no_updates_subtitle": "No tasks were changed in the period: {period}",
        "no_updates_body": "No activity recorded in the period.",
        # ── Periodic types ────────────────────────────────────────────────────
        "daily_type": "Daily",
        "daily_period": "Day {date}",
        "weekly_type": "Weekly",
        "weekly_period": "Week of {start} to {end}",
        # ── Filenames ─────────────────────────────────────────────────────────
        "filename_executive": "executive_report_{ts}.pdf",
        "filename_province": "province_report_{folder_id}_{ts}.pdf",
        "filename_daily": "daily_report_{ts}.pdf",
        "filename_weekly": "weekly_report_{ts}.pdf",
    },
}


def get_strings(lang: str) -> dict[str, str]:
    return STRINGS.get(lang, STRINGS["pt"])
