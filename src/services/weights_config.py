"""
Pesos de disciplinas, atividades e reconstrução de curva de evolução temporal.

Hierarquia:
  Pasta (Província)
    └─ Lista (módulo: Estúdio / Site FM)
         └─ Tarefa = Disciplina (ex.: Obras Civis, Instalações Elétricas)
              └─ Subtarefa = Atividade (ex.: Paredes, Pisos, Tetos)

Critérios usados para atribuição dos pesos:
  - Complexidade técnica e mão-de-obra especializada
  - Impacto no cronograma (caminho crítico)
  - Custo relativo ao total da disciplina
  - Risco de retrabalho se executado fora de sequência
"""

import re
import unicodedata
from datetime import datetime


def _norm(text: str) -> str:
    """Normaliza nome para matching: sem acentos, lowercase, só alfanuméricos+espaços."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower().strip()
    cleaned = re.sub(r"[^a-z0-9 ]", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


# ── Pesos relativos das Disciplinas (Tarefas) dentro de cada Lista ────────────
# Valores são relativos — normalizados no cálculo (não precisam somar 1.0).
# Quanto maior o valor, maior a participação no progresso da lista.

TASK_WEIGHTS: dict[str, float] = {
    # ── Padrão Estúdios (português) ───────────────────────────────────────────
    # Obras civis: fundação + paredes + pisos + tetos — maior esforço de mão-de-obra
    "obras civis": 30.0,
    # Instalação de equipamentos: core técnico do estúdio, custo elevado
    "instalacao de equipamentos do estudio": 25.0,
    # Mobiliário acústico: especializado, impacta qualidade final do estúdio
    "instalacao de mobiliario acustico do estudio": 20.0,
    # Pré-comissionamento: verificações técnicas críticas antes do aceite
    "testes de pre comissionamento": 10.0,
    # SAT: validação formal com cliente — curto, mas imprescindível
    "testes de aceitacao sat": 10.0,
    # Aceitação / transferência: marco administrativo
    "aceitacao transferencia": 3.0,
    # Encerramento: marco de fim de obra
    "fim das obras": 2.0,

    # ── Padrão HQ Studio (inglês — Luanda HQ) ─────────────────────────────────
    "civil works": 30.0,
    "studio equipment installation": 25.0,
    "studio acoustic furniture installation": 15.0,
    "studio furniture installation": 13.0,
    "pre commissioning tests": 10.0,
    "sat accepting tests": 5.0,
    "end of work": 2.0,

    # ── Padrão Site FM ────────────────────────────────────────────────────────
    # Variantes de aceitação/transferência
    "aceitacao e transferencia": 3.0,   # variante de "aceitacao transferencia"
    # Instalação genérica de equipamentos FM (quando não há "Levantamento da Torre + RF")
    "instalacao de equipamentos": 20.0,
    # Torre + RF: coração da transmissão — maior valor agregado e risco
    "levantamento da torre rf": 30.0,
    # Elétricas: energia contínua + backup + aterramento — caminho crítico
    "instalacoes eletricas": 25.0,
    # Fundação: civil pesado, irreversível — erro aqui paralisa tudo
    "fundacao da base da torre": 20.0,
    # Logística: transporte e desembalagem dos equipamentos
    "logistica transporte de conteineres": 7.0,
    # Bases menores de concreto (antena satelital e gerador)
    "base de concreto para antena satelital": 5.0,
    "base de concreto para gerador": 5.0,
    # Fechamento de janela: vedação civil
    "fechamento de janela": 5.0,
    # Pintura interna: acabamento estético, menor impacto operacional
    "pintura interna": 3.0,
}


# ── Pesos relativos das Atividades (Subtarefas) por Disciplina ────────────────
# Chave externa: nome normalizado da tarefa pai (disciplina)
# Chave interna: nome normalizado da subtarefa (atividade)
# Fallback automático: peso 1.0 (igual) para nomes não mapeados

SUBTASK_WEIGHTS: dict[str, dict[str, float]] = {
    # Obras Civis — parede tem maior área e custo que piso ou teto
    "obras civis": {
        "paredes": 45.0,
        "pisos": 30.0,
        "tetos": 25.0,
    },
    # Civil Works (HQ inglês) — inclui limpeza inicial de obra
    "civil works": {
        "paredes": 40.0,
        "pisos": 30.0,
        "tetos": 20.0,
        "limpeza": 10.0,
    },
    # Instalação de Equipamentos — mesa de controle é mais complexa
    "instalacao de equipamentos do estudio": {
        "mesa de controle": 35.0,
        "computadores e software": 30.0,
        "monitores de audio": 20.0,
        "instalacao de microfones": 15.0,
    },
    # Mobiliário Acústico — revestimento cobre maior área
    "instalacao de mobiliario acustico do estudio": {
        "revestimento acustico": 35.0,
        "paineis acusticos": 30.0,
        "ripado nas paredes": 20.0,
        "nuvens acusticas": 15.0,
    },
    # Testes de Pré-Comissionamento — interligação é mais trabalhosa
    "testes de pre comissionamento": {
        "interligacao de equipamentos": 45.0,
        "teste de sinal de audio": 35.0,
        "qualidade de audio": 20.0,
    },
    # Pre-Commissioning Tests (HQ) — console é ponto de integração central
    "pre commissioning tests": {
        "console wheatstone": 25.0,
        "aoip testes": 20.0,
        "automation software": 20.0,
        "studio power up": 15.0,
        "check drawings": 10.0,
        "labeling": 5.0,
        "inventory list": 5.0,
    },
    # Testes SAT — verificação de parâmetros é mais técnica
    "testes de aceitacao sat": {
        "verificacao de parametros": 40.0,
        "qualidade de audio e video": 35.0,
        "producao de relatorio sat": 25.0,
    },
    # SAT Accepting Tests (HQ)
    "sat accepting tests": {
        "console wheatstone": 25.0,
        "aoip testes": 20.0,
        "automation software": 20.0,
        "studio power up": 15.0,
        "check drawings": 10.0,
        "labeling": 5.0,
        "inventory list": 5.0,
    },
    # Fundação da Base da Torre — concretagem e içamento são críticos
    "fundacao da base da torre": {
        "derramamento de concreto": 25.0,
        "levantamento da torre": 25.0,
        "cura de concreto": 20.0,
        "nivelamento": 10.0,
        "preparacao da forma": 10.0,
        "estudo de solo": 5.0,
        "alocacao de acessorios": 5.0,
    },
    # Instalações Elétricas — gerador e UPS são críticos para continuidade
    "instalacoes eletricas": {
        "gerador 165kva": 25.0,
        "sistemas ups": 25.0,
        "sistema de aterramento": 20.0,
        "ar condicionado": 15.0,
        "supressor de surtos": 10.0,
        "bandeja de cabos": 5.0,
    },
    # Levantamento da Torre + RF — antena e transmissores são core da emissão
    "levantamento da torre rf": {
        "sistema antena fm": 35.0,
        "transmissores suportes": 30.0,
        "combinador 5 vias": 20.0,
        "desidratador": 15.0,
    },
    # Fechamento de Janela — bloco é a maior parte do trabalho
    "fechamento de janela": {
        "bloco de cimento": 45.0,
        "gesso jateado": 35.0,
        "cura de concreto": 20.0,
    },
    # Logística
    "logistica transporte de conteineres": {
        "desembalagem": 100.0,
    },
    # Pintura interna
    "pintura interna": {
        "pintura de teto": 50.0,
        "pintura de parede": 50.0,
    },
    # Bases menores de concreto
    "base de concreto para antena satelital": {
        "cura de concreto": 100.0,
    },
    "base de concreto para gerador": {
        "cura de concreto": 100.0,
    },
}


# ── Funções de cálculo ────────────────────────────────────────────────────────

def compute_task_progress(
    task_name: str, task_done: bool, subtasks: list[dict]
) -> float:
    """
    Progresso 0..1 de uma disciplina usando pesos das subtarefas.
    - Se o pai está concluído → 1.0 (status do engenheiro é autoritativo).
    - Se não há subtarefas e pai aberto → 0.0.
    - Se há subtarefas e pai aberto → progresso ponderado pelas subtarefas.
    subtasks: [{'name': str, 'is_done': bool}, ...]
    """
    if task_done:
        return 1.0

    if not subtasks:
        return 0.0

    sub_dict = SUBTASK_WEIGHTS.get(_norm(task_name), {})
    total_w = 0.0
    done_w = 0.0
    for sub in subtasks:
        w = sub_dict.get(_norm(sub["name"]), 1.0)
        total_w += w
        if sub["is_done"]:
            done_w += w
    return done_w / total_w if total_w > 0 else 0.0


def compute_list_progress(tasks: list[dict]) -> tuple[float, list[dict]]:
    """
    Progresso ponderado de uma lista (conjunto de disciplinas).
    tasks: [{'name': str, 'is_done': bool, 'subtasks': [...], 'task_id': str}, ...]
    Retorna: (progress 0..1, detalhes por tarefa)
    """
    raw_weights: list[float] = []
    for task in tasks:
        raw_weights.append(TASK_WEIGHTS.get(_norm(task["name"]), 1.0))
    total_w = sum(raw_weights)

    details: list[dict] = []
    weighted_sum = 0.0
    for task, raw_w in zip(tasks, raw_weights):
        norm_w = raw_w / total_w if total_w > 0 else 0.0
        task_prog = compute_task_progress(
            task["name"], task["is_done"], task.get("subtasks", [])
        )
        weighted_sum += norm_w * task_prog

        sub_dict = SUBTASK_WEIGHTS.get(_norm(task["name"]), {})
        sub_raws = [
            sub_dict.get(_norm(s["name"]), 1.0) for s in task.get("subtasks", [])
        ]
        sub_total = sum(sub_raws)
        sub_details = []
        for sub, sw in zip(task.get("subtasks", []), sub_raws):
            sub_details.append({
                "name": sub["name"],
                "is_done": sub["is_done"],
                "weight_raw": sw,
                "weight_norm": sw / sub_total if sub_total > 0 else 0.0,
            })

        details.append({
            "name": task["name"],
            "task_id": task.get("task_id", ""),
            "is_done": task["is_done"],
            "weight_raw": raw_w,
            "weight_norm": norm_w,
            "progress": task_prog,
            "subtasks": sub_details,
        })

    return weighted_sum, details


def compute_province_progress(lists_data: list[dict]) -> dict:
    """
    Calcula progresso ponderado de uma província com pesos de dois níveis.
    lists_data: saída de CacheRepository.get_tasks_for_weighted_progress()

    Retorna estrutura compatível com get_weighted_progress() +
    campo 'task_details' em cada disciplina.
    """
    disciplines: list[dict] = []
    n_lists = len(lists_data)
    folder_progress_sum = 0.0

    simple_total_tasks = 0
    simple_done_tasks = 0

    for lst in lists_data:
        list_prog, task_details = compute_list_progress(lst["tasks"])
        folder_progress_sum += list_prog

        total_tasks = lst["total_tasks"]
        completed = lst["completed_tasks"]
        simple_total_tasks += total_tasks
        simple_done_tasks += completed
        simple_rate = completed / total_tasks if total_tasks > 0 else 0.0

        disciplines.append({
            "list_id": lst["list_id"],
            "name": lst["name"],
            # Cada lista tem peso igual dentro da pasta
            "weight": 1.0 / n_lists if n_lists > 0 else 0.0,
            "weight_pct": round(100.0 / n_lists, 1) if n_lists > 0 else 0.0,
            "completion_rate": round(list_prog, 4),
            "simple_completion_rate": round(simple_rate, 4),
            "total_tasks": total_tasks,
            "completed_tasks": completed,
            "overdue_tasks": lst["overdue_tasks"],
            "weighted_contribution": round(list_prog / n_lists, 4) if n_lists > 0 else 0.0,
            "task_details": task_details,
        })

    folder_weighted = folder_progress_sum / n_lists if n_lists > 0 else 0.0
    simple_progress = simple_done_tasks / simple_total_tasks if simple_total_tasks > 0 else 0.0

    return {
        "disciplines": disciplines,
        "weighted_progress": round(folder_weighted, 4),
        "simple_progress": round(simple_progress, 4),
        "weights_configured": True,
        "weights_sum": 100.0,
    }


def build_province_evolution(lists_data: list[dict], now: datetime) -> dict:
    """
    Reconstrói a curva de progresso ponderado ao longo do tempo para uma província.

    lists_data: saída de CacheRepository.get_folder_tasks_for_evolution() —
        [{list_id, name, total_tasks, completed_tasks, tasks:
            [{task_id, name, is_done, date_created, date_closed, subtasks:[]}]}]

    Retorna:
        {
          "start_date": str | None,     # ISO da data de criação da 1ª tarefa
          "current_progress": float,    # progresso ponderado atual (0-1)
          "points": [{"date": str, "progress": float}]  # série temporal
        }

    Algoritmo:
        - Cada lista tem peso igual: 1/n_lists
        - Dentro de cada lista, tarefas têm peso TASK_WEIGHTS (normalizado)
        - Contribuição de uma tarefa ao progresso da pasta = weight_norm / n_lists
        - Ao marcar uma tarefa como concluída, sua contribuição é adicionada cumulativamente
        - O eixo X é reconstruído a partir de date_closed de cada tarefa concluída
    """
    n_lists = len(lists_data)
    if not n_lists:
        return {"start_date": None, "current_progress": 0.0, "points": []}

    events: list[tuple[datetime, float]] = []   # (date_closed, contribution)
    all_created: list[datetime] = []
    current_progress = 0.0

    for lst in lists_data:
        tasks = lst["tasks"]
        if not tasks:
            continue
        raw_weights = [TASK_WEIGHTS.get(_norm(t["name"]), 1.0) for t in tasks]
        total_w = sum(raw_weights)

        list_prog = 0.0
        for task, raw_w in zip(tasks, raw_weights):
            norm_w = raw_w / total_w if total_w > 0 else 0.0
            contrib = norm_w / n_lists

            if task.get("date_created"):
                all_created.append(task["date_created"])

            if task["is_done"]:
                list_prog += norm_w
                dc = task.get("date_closed")
                if dc:
                    events.append((dc, contrib))

        current_progress += list_prog / n_lists

    start_date = min(all_created) if all_created else None
    events.sort(key=lambda x: x[0])

    points: list[dict] = []
    if start_date:
        points.append({"date": start_date.isoformat(), "progress": 0.0})

    cumulative = 0.0
    for dc, contrib in events:
        cumulative = min(cumulative + contrib, 1.0)
        if start_date is None or dc >= start_date:
            points.append({"date": dc.isoformat(), "progress": round(cumulative, 4)})

    today_iso = now.isoformat()
    if not points or points[-1]["date"] < today_iso:
        points.append({"date": today_iso, "progress": round(current_progress, 4)})

    return {
        "start_date": start_date.isoformat() if start_date else None,
        "current_progress": round(current_progress, 4),
        "points": points,
    }
