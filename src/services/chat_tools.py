"""
Definições das tools do agente de chat e dispatcher para DashboardService/CacheRepository.
Todas as tools são read-only sobre o cache SQLite local.
"""
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.repositories.cache_repository import CacheRepository
from src.services.dashboard_service import DashboardService
from src.services.weights_config import _norm, compute_province_progress


TOOL_DEFINITIONS: list[dict] = [
    # ── Ferramentas temporais (primeiro para garantir prioridade no roteamento) ──
    {
        "name": "get_recent_changes",
        "description": (
            "USAR OBRIGATORIAMENTE quando a pergunta mencionar um período de tempo: "
            "'hoje', 'ontem', 'essa semana', 'este mês', 'últimos X dias', 'recentemente'. "
            "Também usar para: 'o que mudou', 'o que foi concluído', 'quais foram concluídas', "
            "'alterações do dia/semana/mês', 'atividade recente', 'novidades do projeto'. "
            "Retorna tarefas concluídas e tarefas com progresso real (Fazendo/Revisão/"
            "Aprovação) agrupadas por status no período. NÃO inclui tarefas recém-criadas "
            "(ainda em planejando) — nunca mencione tarefas apenas criadas nas respostas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week", "month"],
                    "description": (
                        "'today' = últimas 24h, 'yesterday' = dia anterior, "
                        "'week' = últimos 7 dias, 'month' = últimos 30 dias"
                    ),
                },
                "folder_name": {
                    "type": "string",
                    "description": "Opcional: filtra por província específica",
                },
            },
            "required": ["period"],
        },
    },
    {
        "name": "list_tasks_by_status",
        "description": (
            "USAR quando a pergunta for sobre o estado atual das tarefas por status, "
            "SEM mencionar período de tempo. Exemplos: 'quais estão em fazendo', "
            "'tarefas em revisão', 'o que está em aprovação', 'quais ainda estão planejando', "
            "'distribuição de status', 'quais tarefas estão em andamento agora'. "
            "Omitir o parâmetro 'status' para ver todos os status disponíveis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Nome exato do status (ex: 'fazendo', 'em revisão', 'aprovação', 'planejando'). Omitir para ver todos.",
                },
                "folder_name": {
                    "type": "string",
                    "description": "Opcional: filtra por província",
                },
            },
        },
    },
    # ── Ferramentas de progresso e visão geral ────────────────────────────────
    {
        "name": "get_overview_kpis",
        "description": (
            "Retorna KPIs gerais do espaço inteiro: total de tarefas, concluídas, atrasadas, "
            "taxa de conclusão e distribuição por status. Use quando o usuário pedir um resumo "
            "geral, panorama, visão geral ou totais — SEM mencionar período de tempo."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_folders",
        "description": (
            "Lista todas as províncias com métricas (total de tarefas, concluídas, atrasadas, "
            "taxa de conclusão). Use para comparar províncias, ver ranking ou descobrir quais existem."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_folder_progress",
        "description": (
            "Retorna o progresso detalhado (EVM) de uma província específica, incluindo breakdown "
            "por módulo/disciplina com pesos. Use quando o usuário perguntar sobre o progresso de "
            "uma província específica pelo nome (ex: 'Kuito', 'Luanda')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_name": {
                    "type": "string",
                    "description": "Nome da província (case-insensitive, aceita variações)",
                }
            },
            "required": ["folder_name"],
        },
    },
    {
        "name": "list_overdue_tasks",
        "description": (
            "Lista tarefas atrasadas (prazo vencido). Pode filtrar por província. "
            "Use para perguntas sobre atrasos, tarefas em atraso, problemas de prazo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_name": {"type": "string", "description": "Opcional: filtra por província"},
                "limit": {"type": "integer", "description": "Máximo de tarefas (padrão 20)", "default": 20},
            },
        },
    },
    {
        "name": "list_upcoming_tasks",
        "description": (
            "Lista tarefas com prazo nos PRÓXIMOS N dias (futuro). Pode filtrar por província. "
            "Use para: próximos vencimentos, agenda, o que está por vir, prazos futuros."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Janela de dias futuros (padrão 30)", "default": 30},
                "folder_name": {"type": "string", "description": "Opcional: filtra por província"},
            },
        },
    },
    {
        "name": "get_assignee_stats",
        "description": (
            "Estatísticas por responsável: tarefas em aberto, concluídas e atrasadas. "
            "Use para: carga de trabalho, quem está sobrecarregado, desempenho da equipe."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_name": {"type": "string", "description": "Opcional: filtra por província"},
            },
        },
    },
    {
        "name": "get_evolution_curve",
        "description": (
            "Retorna a curva de progresso ponderado ao longo do tempo para todas as províncias. "
            "Use para: evolução histórica, trajetória, crescimento, tendência de progresso."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _dt_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%d/%m/%Y")


async def _resolve_folder(
    name: str, db: AsyncSession, space_id: str
) -> tuple[str | None, list[str]]:
    """Resolve nome de província para folder_id. Retorna (folder_id, candidatos_se_ambíguo)."""
    repo = CacheRepository(db)
    folders = await repo.get_all_folders(space_id)
    if not folders:
        return None, []

    norm_input = _norm(name)

    exact = [f for f in folders if _norm(f.name) == norm_input]
    if len(exact) == 1:
        return exact[0].folder_id, []

    partial = [f for f in folders if norm_input in _norm(f.name)]
    if len(partial) == 1:
        return partial[0].folder_id, []
    if len(partial) > 1:
        return None, [f.name for f in partial]

    return None, [f.name for f in folders]


def _to_json(obj: dict | list) -> str:
    return json.dumps(obj, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o), ensure_ascii=False)


async def dispatch_tool(
    name: str, input_data: dict, db: AsyncSession, space_id: str
) -> tuple[str, dict | None]:
    """
    Executa a tool e retorna (texto_para_claude, dados_para_grafico).
    O texto_para_claude é o que o modelo vê. dados_para_grafico é usado pelo _build_chart.
    """
    if not space_id:
        return '{"error": "CLICKUP_DEFAULT_SPACE_ID não configurado."}', None

    repo = CacheRepository(db)
    svc = DashboardService(db)

    try:
        if name == "get_overview_kpis":
            overview = await svc.get_overview(space_id)
            data = overview.model_dump()
            claude_data = {
                "total_tasks": data["total_tasks"],
                "completed_tasks": data["completed_tasks"],
                "completion_rate_pct": round(data["completion_rate"] * 100, 1),
                "overdue_tasks": data["overdue_tasks"],
                "tasks_without_due_date": data["tasks_without_due_date"],
                "total_folders": data["total_folders"],
                "total_lists": data["total_lists"],
                "status_distribution": data["status_distribution"],
            }
            return _to_json(claude_data), {"kpis": claude_data}

        if name == "list_folders":
            folders = await svc.get_folders(space_id)
            data = [
                {
                    "name": f.name,
                    "folder_id": f.folder_id,
                    "total_tasks": f.total_tasks,
                    "completed_tasks": f.completed_tasks,
                    "overdue_tasks": f.overdue_tasks,
                    "completion_rate_pct": round(f.completion_rate * 100, 1),
                }
                for f in folders
            ]
            return _to_json({"folders": data}), {"folders": data}

        if name == "get_folder_progress":
            folder_name = input_data.get("folder_name", "")
            folder_id, candidates = await _resolve_folder(folder_name, db, space_id)
            if not folder_id:
                msg = {"error": "not_found", "searched": folder_name, "available": candidates}
                return _to_json(msg), None

            kpis = await repo.get_folder_kpis(folder_id)
            lists_data = await repo.get_tasks_for_weighted_progress(folder_id)
            evm = compute_province_progress(lists_data)

            folder_obj = await repo.get_folder_by_id(folder_id)
            resolved_name = folder_obj.name if folder_obj else folder_name

            disciplines_summary = [
                {
                    "name": d["name"],
                    "completion_rate_pct": round(d["completion_rate"] * 100, 1),
                    "weight_pct": d["weight_pct"],
                    "total_tasks": d["total_tasks"],
                    "completed_tasks": d["completed_tasks"],
                    "overdue_tasks": d["overdue_tasks"],
                }
                for d in evm["disciplines"]
            ]

            claude_data = {
                "folder_name": resolved_name,
                "folder_id": folder_id,
                "weighted_progress_pct": round(evm["weighted_progress"] * 100, 1),
                "simple_progress_pct": round(evm["simple_progress"] * 100, 1),
                "total_tasks": kpis["total_tasks"],
                "completed_tasks": kpis["completed_tasks"],
                "overdue_tasks": kpis["overdue_tasks"],
                "disciplines": disciplines_summary,
            }
            return _to_json(claude_data), {"folder_name": resolved_name, "disciplines": disciplines_summary, "weighted_progress_pct": claude_data["weighted_progress_pct"]}

        if name == "list_overdue_tasks":
            folder_name = input_data.get("folder_name")
            limit = int(input_data.get("limit", 20))

            if folder_name:
                folder_id, candidates = await _resolve_folder(folder_name, db, space_id)
                if not folder_id:
                    msg = {"error": "not_found", "searched": folder_name, "available": candidates}
                    return _to_json(msg), None
                raw = await repo.get_overdue_tasks_by_folder(folder_id, limit)
                for t in raw:
                    t["folder_name"] = folder_name
            else:
                raw = await repo.get_overdue_tasks_detail(space_id, limit)

            tasks = [
                {
                    "name": t["name"],
                    "folder_name": t.get("folder_name", "—"),
                    "list_name": t["list_name"],
                    "due_date": _dt_str(t.get("due_date")) or "N/D",
                    "days_overdue": t.get("days_overdue", 0),
                    "assignees": ", ".join(t.get("assignees", [])) or "N/D",
                    "url": t.get("url"),
                }
                for t in raw
            ]
            claude_data = {"total_overdue": len(tasks), "tasks": tasks[:20]}
            return _to_json(claude_data), {"tasks": tasks}

        if name == "list_upcoming_tasks":
            days = int(input_data.get("days", 30))
            folder_name = input_data.get("folder_name")

            if folder_name:
                folder_id, candidates = await _resolve_folder(folder_name, db, space_id)
                if not folder_id:
                    msg = {"error": "not_found", "searched": folder_name, "available": candidates}
                    return _to_json(msg), None
                raw = await repo.get_upcoming_tasks_by_folder(folder_id, days)
                for t in raw:
                    t["folder_name"] = folder_name
            else:
                raw = await svc.get_upcoming_tasks(space_id, days)
                raw = [r.model_dump() if hasattr(r, "model_dump") else r for r in raw]

            tasks = []
            for t in raw[:30]:
                due = t.get("due_date") or t.get("due_date_fmt", "N/D")
                if isinstance(due, datetime):
                    due = due.strftime("%d/%m/%Y")
                tasks.append({
                    "name": t.get("name", ""),
                    "folder_name": t.get("folder_name", "—"),
                    "list_name": t.get("list_name", ""),
                    "due_date": str(due) if due else "N/D",
                    "assignees": t.get("assignees_str") or ", ".join(t.get("assignees", [])) or "N/D",
                    "url": t.get("url"),
                })
            claude_data = {"days_window": days, "total": len(tasks), "tasks": tasks}
            return _to_json(claude_data), {"tasks": tasks, "days": days}

        if name == "get_assignee_stats":
            folder_name = input_data.get("folder_name")

            if folder_name:
                folder_id, candidates = await _resolve_folder(folder_name, db, space_id)
                if not folder_id:
                    msg = {"error": "not_found", "searched": folder_name, "available": candidates}
                    return _to_json(msg), None
                stats = await repo.get_assignee_stats_by_folder(folder_id)
            else:
                stats = await svc.get_assignee_stats(space_id)
                stats = [s.model_dump() if hasattr(s, "model_dump") else s for s in stats]

            claude_data = {"stats": stats[:20]}
            return _to_json(claude_data), {"stats": stats[:20]}

        if name == "list_tasks_by_status":
            status_filter = input_data.get("status")
            folder_name = input_data.get("folder_name")
            folder_id = None
            if folder_name:
                folder_id, candidates = await _resolve_folder(folder_name, db, space_id)
                if not folder_id:
                    return _to_json({"error": "not_found", "available": candidates}), None

            result = await repo.get_tasks_by_status(space_id, status_filter, folder_id)
            return _to_json(result), {"status_data": result}

        if name == "get_recent_changes":
            from datetime import timedelta, timezone
            period = input_data.get("period", "today")
            folder_name = input_data.get("folder_name")
            now = datetime.utcnow()
            if period == "today":
                since = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period == "yesterday":
                yesterday = now - timedelta(days=1)
                since = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period == "week":
                since = now - timedelta(days=7)
            else:  # month
                since = now - timedelta(days=30)

            changes = await repo.get_recent_changes(space_id, since)

            if folder_name:
                folder_id, candidates = await _resolve_folder(folder_name, db, space_id)
                if folder_id:
                    folder_obj = await repo.get_folder_by_id(folder_id)
                    fname = folder_obj.name if folder_obj else folder_name
                    changes["completed"] = [t for t in changes["completed"] if t["folder_name"] == fname]
                    changes["by_status"] = {
                        s: [t for t in tasks if t["folder_name"] == fname]
                        for s, tasks in changes["by_status"].items()
                    }

            period_labels = {"today": "hoje", "yesterday": "ontem", "week": "nos últimos 7 dias", "month": "nos últimos 30 dias"}
            by_status_summary = {
                status: tasks[:20]
                for status, tasks in changes["by_status"].items()
                if tasks
            }
            claude_data = {
                "period": period_labels.get(period, period),
                "completed_count": len(changes["completed"]),
                "active_statuses": {s: len(t) for s, t in by_status_summary.items()},
                "completed": changes["completed"][:20],
                "by_status": by_status_summary,
            }
            return _to_json(claude_data), {"changes": claude_data}

        if name == "get_evolution_curve":
            evolution = await svc.get_evolution_data(space_id)
            # Para Claude: resumo por província (sem os pontos detalhados)
            summary = [
                {
                    "name": p["name"],
                    "current_progress_pct": round(p["current_progress"] * 100, 1),
                    "start_date": p["start_date"][:10] if p.get("start_date") else None,
                }
                for p in evolution
            ]
            # Para o gráfico: inclui os pontos
            chart_data = [
                {
                    "name": p["name"],
                    "points": [
                        {"date": pt["date"][:10], "value": round(pt["progress"] * 100, 1)}
                        for pt in p.get("points", [])
                    ],
                }
                for p in evolution
            ]
            return _to_json({"provinces": summary}), {"series": chart_data}

        return '{"error": "tool desconhecida"}', None

    except Exception as exc:
        return _to_json({"error": str(exc)}), None
