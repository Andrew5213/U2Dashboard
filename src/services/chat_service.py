"""
Orquestrador do loop agentic: Claude Haiku + tool use.
"""
import time
import anthropic
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.core.logging import logger
from src.models.chat_schemas import ChartPayload, ChatResponse
from src.services.chat_tools import TOOL_DEFINITIONS, dispatch_tool


_SYSTEM_PROMPT = """Você é o Assistente U2, gestor de projetos da U2 Broadcast Angola.
Sua função é acompanhar o andamento das obras de instalação de estúdios de rádio e sites FM nas províncias angolanas.

## Contexto do projeto
Cada **província** tem módulos de trabalho (Studio e FM Site). Cada módulo é dividido em disciplinas como Obras Civis, Instalações Elétricas, etc. O progresso é calculado com base no peso de cada disciplina no custo total da obra.

## Tom e personalidade
- Fale como um gestor de projetos experiente — direto, seguro, sem rodeios
- Use linguagem natural, não robótica: prefira "Kuito está em 42% de conclusão" a "O valor de conclusão_rate_pct é 42"
- Seja conciso: responda em 3 a 6 linhas, exceto quando precisar listar muitos itens
- Use **negrito** para destacar números e nomes de províncias
- Quando a resposta for longa, use tópicos curtos com `-`

## Roteamento obrigatório de ferramentas

Siga esta tabela sem exceção — ela define qual ferramenta usar para cada tipo de pergunta:

| Pergunta contém... | Ferramenta obrigatória |
|---|---|
| "hoje", "ontem", "essa semana", "este mês", "essa semana", "últimos X dias", "mudou", "alterou", "foi concluído", "concluídas recentemente", "atividade recente", "novidades" | `get_recent_changes` |
| "está em fazendo", "estão em revisão", "em aprovação", "qual o status", "tarefas em andamento", "distribuição de status" | `list_tasks_by_status` |
| nome de uma província específica + "progresso" | `get_folder_progress` |
| comparação entre províncias, ranking | `list_folders` |
| resumo geral, visão geral, totais | `get_overview_kpis` |
| atrasadas, atraso, overdue | `list_overdue_tasks` |
| vence, prazo, próximas, agenda | `list_upcoming_tasks` |
| equipe, responsável, carga de trabalho | `get_assignee_stats` |
| evolução, histórico, curva, tendência | `get_evolution_curve` |

## Regras absolutas
1. **Nunca mencione detalhes técnicos internos**: não fale em "cache", "banco de dados", "API", "snapshots", "ferramentas", "sistema" ou qualquer termo de infraestrutura
2. **Quando um dado não existir**, diga simplesmente "Esse dado não está disponível" ou "Não tenho essa informação no momento" — jamais explique o motivo técnico
3. **Nunca invente dados** — use apenas o que as ferramentas retornam
4. Se a província não for encontrada, liste as disponíveis de forma amigável: "Não encontrei essa província. As disponíveis são: ..."
5. Datas sempre no formato **DD/MM/AAAA**
6. Sempre busque os dados com as ferramentas antes de responder"""

# Mapeia o nome da tool para o tipo de gráfico preferido
_TOOL_CHART_TYPE: dict[str, str] = {
    "get_overview_kpis": "kpi",
    "list_folders": "bar",
    "get_folder_progress": "bar",
    "list_overdue_tasks": "table",
    "list_upcoming_tasks": "table",
    "get_assignee_stats": "bar",
    "get_evolution_curve": "line",
}

# Prioridade para escolher qual tool gera o gráfico quando há múltiplas chamadas
_TOOL_PRIORITY: dict[str, int] = {
    "get_folder_progress": 0,
    "list_folders": 1,
    "get_overview_kpis": 2,
    "get_assignee_stats": 3,
    "get_evolution_curve": 4,
    "list_tasks_by_status": 5,
    "get_recent_changes": 6,
    "list_overdue_tasks": 7,
    "list_upcoming_tasks": 8,
}


_TEMPORAL_KEYWORDS = {
    "hoje", "ontem", "semana", "mês", "mes", "semanas", "meses",
    "mudou", "mudaram", "mudança", "mudanças", "alterou", "alteraram",
    "alteração", "alterações", "alteracoes", "alteracao",
    "concluiu", "concluíram", "concluiram", "concluída", "concluidas",
    "concluídas", "conclusão", "recente", "recentes", "novidade",
    "novidades", "atividade", "atividades", "último", "últimos",
    "ultimos", "ultimo", "período", "periodo",
}

_STATUS_KEYWORDS = {
    "fazendo", "revisão", "revisao", "aprovação", "aprovacao",
    "andamento", "em andamento", "em fazendo", "em revisão",
    "em revisao", "em aprovação", "em aprovacao",
    "distribuição de status", "distribuicao de status",
}


def _detect_forced_tool(message: str) -> str | None:
    """Detecta keywords no texto e retorna a ferramenta que deve ser forçada."""
    words = set(message.lower().replace(",", " ").replace("?", " ").split())
    if words & _TEMPORAL_KEYWORDS:
        return "get_recent_changes"
    if words & _STATUS_KEYWORDS:
        return "list_tasks_by_status"
    return None


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def ask(self, message: str) -> ChatResponse:
        start = time.monotonic()
        messages: list[dict] = [{"role": "user", "content": message}]
        tools_used: list[str] = []
        # Tracks (tool_name, raw_result_dict) for chart building
        tool_results_raw: list[tuple[str, dict]] = []
        forced_tool = _detect_forced_tool(message)

        try:
            for iteration in range(1, settings.chat_max_iterations + 1):
                # Na primeira iteração, força a ferramenta certa se detectada por keywords
                tool_choice: dict = {"type": "auto"}
                if iteration == 1 and forced_tool:
                    tool_choice = {"type": "tool", "name": forced_tool}
                    logger.info(f"Chat: forçando ferramenta '{forced_tool}' por keywords")

                response = await self._client.messages.create(
                    model=settings.chat_model,
                    max_tokens=settings.chat_max_tokens,
                    system=_SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    tool_choice=tool_choice,
                    messages=messages,
                )

                logger.info(
                    f"Chat iter={iteration} stop={response.stop_reason} "
                    f"out_tokens={response.usage.output_tokens}"
                )

                if response.stop_reason == "end_turn":
                    text = " ".join(
                        block.text for block in response.content if hasattr(block, "text")
                    ).strip()
                    chart = self._build_chart(tool_results_raw)
                    elapsed = round(time.monotonic() - start, 2)
                    logger.info(f"Chat ok em {elapsed}s tools={tools_used}")
                    return ChatResponse(
                        text=text,
                        chart=chart,
                        tools_used=tools_used,
                        iterations=iteration,
                    )

                if response.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": response.content})
                    result_blocks = []

                    for block in response.content:
                        if block.type != "tool_use":
                            continue

                        tools_used.append(block.name)
                        logger.info(f"Tool call: {block.name}({block.input})")

                        claude_text, raw_data = await dispatch_tool(
                            block.name, block.input, self._db, settings.clickup_default_space_id
                        )
                        if raw_data is not None:
                            tool_results_raw.append((block.name, raw_data))

                        result_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": claude_text,
                        })

                    messages.append({"role": "user", "content": result_blocks})
                    continue

                # stop_reason inesperado — encerra com o que tiver
                break

            # Esgotou iterações
            last_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    last_text += block.text
            return ChatResponse(
                text=last_text.strip() or "Não consegui processar a sua pergunta. Tente novamente.",
                tools_used=tools_used,
                iterations=settings.chat_max_iterations,
            )

        except anthropic.APIError as exc:
            logger.error(f"Anthropic API error: {exc}")
            return ChatResponse(
                success=False,
                text="O assistente está temporariamente indisponível. Tente novamente em alguns instantes.",
                error=str(exc),
                tools_used=tools_used,
            )

    def _build_chart(self, tool_results_raw: list[tuple[str, dict]]) -> ChartPayload | None:
        if not tool_results_raw:
            return None

        # Escolhe a tool de maior prioridade para o gráfico
        best = min(
            tool_results_raw,
            key=lambda x: _TOOL_PRIORITY.get(x[0], 99),
        )
        tool_name, raw = best

        try:
            if tool_name == "get_overview_kpis":
                kpis = raw.get("kpis", {})
                return ChartPayload(
                    type="kpi",
                    title="Visão Geral do Espaço",
                    data=[
                        {"label": "Total de Tarefas", "value": kpis.get("total_tasks", 0)},
                        {"label": "Concluídas", "value": kpis.get("completed_tasks", 0)},
                        {"label": "Atrasadas", "value": kpis.get("overdue_tasks", 0)},
                        {"label": "Progresso", "value": f"{kpis.get('completion_rate_pct', 0)}%"},
                        {"label": "Províncias", "value": kpis.get("total_folders", 0)},
                        {"label": "Módulos", "value": kpis.get("total_lists", 0)},
                    ],
                )

            if tool_name == "list_folders":
                folders = raw.get("folders", [])
                return ChartPayload(
                    type="bar",
                    title="Progresso por Província (%)",
                    data={
                        "categories": [f["name"] for f in folders],
                        "series": [
                            {
                                "name": "Progresso",
                                "data": [f["completion_rate_pct"] for f in folders],
                            }
                        ],
                    },
                )

            if tool_name == "get_folder_progress":
                disciplines = raw.get("disciplines", [])
                name = raw.get("folder_name", "Província")
                return ChartPayload(
                    type="bar",
                    title=f"Progresso por Disciplina — {name} (%)",
                    data={
                        "categories": [d["name"] for d in disciplines],
                        "series": [
                            {
                                "name": "Progresso",
                                "data": [d["completion_rate_pct"] for d in disciplines],
                            }
                        ],
                    },
                )

            if tool_name == "get_assignee_stats":
                stats = raw.get("stats", [])[:15]
                return ChartPayload(
                    type="bar",
                    title="Tarefas por Responsável",
                    data={
                        "categories": [s["assignee"] for s in stats],
                        "series": [
                            {"name": "Em Aberto", "data": [s["open"] for s in stats]},
                            {"name": "Concluídas", "data": [s["completed"] for s in stats]},
                            {"name": "Atrasadas", "data": [s["overdue"] for s in stats]},
                        ],
                        "stacked": True,
                    },
                )

            if tool_name == "list_overdue_tasks":
                tasks = raw.get("tasks", [])
                return ChartPayload(
                    type="table",
                    title="Tarefas Atrasadas",
                    data={
                        "headers": ["Tarefa", "Província", "Lista", "Prazo", "Dias", "Responsável"],
                        "rows": [
                            [
                                t.get("name", ""),
                                t.get("folder_name", "—"),
                                t.get("list_name", ""),
                                t.get("due_date", ""),
                                t.get("days_overdue", ""),
                                t.get("assignees", ""),
                            ]
                            for t in tasks
                        ],
                    },
                )

            if tool_name == "list_upcoming_tasks":
                tasks = raw.get("tasks", [])
                days = raw.get("days", 30)
                return ChartPayload(
                    type="table",
                    title=f"Próximas Tarefas ({days} dias)",
                    data={
                        "headers": ["Tarefa", "Província", "Lista", "Prazo", "Responsável"],
                        "rows": [
                            [
                                t.get("name", ""),
                                t.get("folder_name", "—"),
                                t.get("list_name", ""),
                                t.get("due_date", ""),
                                t.get("assignees", ""),
                            ]
                            for t in tasks
                        ],
                    },
                )

            if tool_name == "list_tasks_by_status":
                sd = raw.get("status_data", raw)
                by_status = sd.get("by_status", {})
                status_filter = sd.get("filter")
                if status_filter:
                    tasks = by_status.get(status_filter.lower(), [])
                    return ChartPayload(
                        type="table",
                        title=f'Tarefas em "{status_filter}"',
                        data={
                            "headers": ["Tarefa", "Província", "Módulo", "Prazo", "Responsável"],
                            "rows": [
                                [t["name"], t["folder_name"], t["list_name"], t.get("due_date") or "—", ", ".join(t.get("assignees", []))]
                                for t in tasks
                            ],
                        },
                    )
                if by_status:
                    return ChartPayload(
                        type="pie",
                        title="Distribuição de tarefas por status",
                        data=[{"name": s.capitalize(), "value": len(ts)} for s, ts in by_status.items()],
                    )
                return None

            if tool_name == "get_recent_changes":
                ch = raw.get("changes", raw)
                period = ch.get("period", "recente")

                # Tabela de concluídas tem prioridade
                completed = ch.get("completed", [])
                if completed:
                    return ChartPayload(
                        type="table",
                        title=f"Tarefas concluídas {period}",
                        data={
                            "headers": ["Tarefa", "Província", "Módulo", "Responsável"],
                            "rows": [
                                [t["name"], t["folder_name"], t["list_name"], ", ".join(t.get("assignees", []))]
                                for t in completed
                            ],
                        },
                    )

                # Se há tarefas em status ativos, mostra gráfico de pizza por status
                by_status = ch.get("by_status", {})
                active = {s: ts for s, ts in by_status.items() if ts}
                if active:
                    return ChartPayload(
                        type="pie",
                        title=f"Tarefas ativas por status {period}",
                        data=[{"name": s.capitalize(), "value": len(ts)} for s, ts in active.items()],
                    )

                created = ch.get("created", [])
                if created:
                    return ChartPayload(
                        type="table",
                        title=f"Tarefas criadas {period}",
                        data={
                            "headers": ["Tarefa", "Província", "Módulo", "Responsável"],
                            "rows": [
                                [t["name"], t["folder_name"], t["list_name"], ", ".join(t.get("assignees", []))]
                                for t in created
                            ],
                        },
                    )
                return None

            if tool_name == "get_evolution_curve":
                series = raw.get("series", [])
                return ChartPayload(
                    type="line",
                    title="Evolução do Progresso por Província (%)",
                    data={"series": series},
                )

        except Exception as exc:
            logger.warning(f"Chart build falhou para {tool_name}: {exc}")

        return None
