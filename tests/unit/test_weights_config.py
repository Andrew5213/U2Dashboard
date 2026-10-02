import pytest
from src.services.weights_config import _norm, TASK_WEIGHTS, SUBTASK_WEIGHTS, compute_list_progress


# ─── Nomes reais do ClickUp devem bater com os pesos configurados ────────────
# (e não cair no fallback de peso igual). Um caso por padrão de projeto.

def test_estudios_pattern_task_and_subtask_match():
    assert _norm("Obras Civis") in TASK_WEIGHTS
    subs = SUBTASK_WEIGHTS[_norm("Instalação de Equipamentos do Estúdio")]
    assert _norm("Instalação da Mesa de Controle") in subs
    assert subs[_norm("Instalação da Mesa de Controle")] == 40.0


def test_site_fm_pattern_task_and_subtask_match():
    assert _norm("Instalações Elétricas") in TASK_WEIGHTS
    subs = SUBTASK_WEIGHTS[_norm("Instalações Elétricas")]
    assert _norm("Bandeja de cabos") in subs
    assert subs[_norm("Bandeja de cabos")] == 13.0


def test_ct_studio_pattern_task_and_subtask_match():
    assert _norm("Obra Civil") in TASK_WEIGHTS
    subs = SUBTASK_WEIGHTS[_norm("Equipamentos")]
    assert _norm("Passagem de Cabos de Audio") in subs
    assert subs[_norm("Passagem de Cabos de Audio")] == 14.0


def test_transmissor_luanda_sul_pattern_task_and_subtask_match():
    assert _norm("Gerador") in TASK_WEIGHTS
    subs = SUBTASK_WEIGHTS[_norm("Gerador")]
    assert _norm("Passagem de cabos do QGBT ao gerador") in subs
    assert subs[_norm("Passagem de cabos do QGBT ao gerador")] == 15.0


# ─── Regra de esforço: roteamento de cabo pesa mais que terminação/montagem ──

def test_cable_routing_outweighs_termination_and_simple_mount():
    subs = SUBTASK_WEIGHTS[_norm("Equipamentos")]
    passagem = subs[_norm("Passagem de Cabos de Audio")]
    solda = subs[_norm("Soldagem de Cabos de Audio")]
    montagem_simples = subs[_norm("Instalação Computadores")]
    assert passagem > solda
    assert passagem > montagem_simples


def test_furniture_installation_weighted_high_ct_studio():
    subs = SUBTASK_WEIGHTS[_norm("Mobiliario")]
    assert subs[_norm("Instalação Moveis")] == max(subs.values())


# ─── compute_list_progress deve refletir pesos reais, não só o fallback ──────

def test_compute_list_progress_uses_real_weights_not_equal_fallback():
    tasks = [
        {
            "task_id": "t1",
            "name": "Obras Civis",
            "is_done": False,
            "subtasks": [
                {"name": "Paredes", "is_done": True},
                {"name": "Pisos", "is_done": False},
                {"name": "Tetos", "is_done": False},
            ],
        },
        {"task_id": "t2", "name": "Fim das Obras", "is_done": False, "subtasks": []},
    ]
    progress, _ = compute_list_progress(tasks)

    # Peso ponderado: Obras Civis (peso 30) domina sobre Fim das Obras (peso 2);
    # dentro de Obras Civis, Paredes (peso 30 de 73) é a única concluída.
    expected = (30 / 32) * (30 / 73)
    assert progress == pytest.approx(expected, abs=0.001)

    # Contagem simples de tarefas-folha daria 1/4 (Paredes de 4 folhas) — bem
    # diferente do resultado ponderado, provando que o peso real está sendo usado.
    simple_flat_rate = 1 / 4
    assert progress != pytest.approx(simple_flat_rate, abs=0.01)


# ─── Curva de evolução ───────────────────────────────────────────────────────
# A evolução e o gráfico de barras precisam fechar no mesmo número. Antes a curva
# só contava disciplinas inteiras fechadas, então províncias como HUAMBO — com
# atividades concluídas e nenhuma disciplina fechada — apareciam com 0%.

from datetime import datetime  # noqa: E402

from src.services.weights_config import build_province_evolution  # noqa: E402


def _lista(disciplina: str, atividades: list[tuple[str, bool]], pai_done: bool = False) -> dict:
    criado = datetime(2026, 1, 1)
    return {
        "list_id": "l1", "name": "Site FM", "total_tasks": 1, "completed_tasks": 0,
        "tasks": [{
            "task_id": "t1", "name": disciplina, "is_done": pai_done,
            "date_created": criado,
            "date_closed": datetime(2026, 9, 30) if pai_done else None,
            "subtasks": [
                {"name": nome, "is_done": done, "date_created": criado,
                 "date_closed": datetime(2026, 9, 30) if done else None}
                for nome, done in atividades
            ],
        }],
    }


def test_atividades_concluidas_movem_a_curva_sem_disciplina_fechada():
    lista = _lista("Gerador", [("Fabricação caixote", True), ("Concretagem base gerador", False)])
    ev = build_province_evolution([lista], datetime(2026, 10, 2))

    assert ev["current_progress"] > 0
    assert len(ev["points"]) > 2  # início + degrau da atividade + hoje


def test_evolucao_bate_com_o_progresso_do_grafico_de_barras():
    lista = _lista("Gerador", [("Fabricação caixote", True), ("Concretagem base gerador", False)])
    ev = build_province_evolution([lista], datetime(2026, 10, 2))
    barras, _ = compute_list_progress(lista["tasks"])

    assert ev["current_progress"] == pytest.approx(barras, abs=1e-4)


def test_disciplina_fechada_vale_um_inteiro_mesmo_com_atividade_aberta():
    lista = _lista("Gerador", [("Fabricação caixote", True), ("Concretagem base gerador", False)],
                   pai_done=True)
    ev = build_province_evolution([lista], datetime(2026, 10, 2))

    assert ev["current_progress"] == pytest.approx(1.0, abs=1e-4)
    # o degrau da atividade e o do fechamento da disciplina somam o total, sem dobrar
    assert ev["points"][-1]["progress"] == pytest.approx(1.0, abs=1e-4)


def test_nada_concluido_fica_em_zero():
    lista = _lista("Gerador", [("Fabricação caixote", False)])
    ev = build_province_evolution([lista], datetime(2026, 10, 2))

    assert ev["current_progress"] == 0.0
    assert all(p["progress"] == 0.0 for p in ev["points"])


def test_atividade_sem_data_de_conclusao_nao_quebra_a_serie():
    lista = _lista("Gerador", [("Fabricação caixote", True)])
    lista["tasks"][0]["subtasks"][0]["date_closed"] = None
    ev = build_province_evolution([lista], datetime(2026, 10, 2))

    # sem data não há degrau, mas o ponto final ainda reflete o progresso real
    assert ev["current_progress"] > 0
    assert ev["points"][-1]["progress"] == pytest.approx(ev["current_progress"], abs=1e-4)
