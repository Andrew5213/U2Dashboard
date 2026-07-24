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
