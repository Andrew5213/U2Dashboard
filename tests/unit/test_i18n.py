"""Versão em inglês da dashboard: o que o servidor entrega para a tradução da tela."""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.models.chat_schemas import ChatRequest
from src.services.chat_service import _SYSTEM_PROMPT, _system_prompt
from src.services.translation import _norm, english_terms, translate


@pytest.fixture(scope="module")
def client():
    import src.main as main
    return TestClient(main.app)    # sem `with`: o lifespan (workers, banco) não é iniciado


class TestTermsScript:
    def test_terms_are_served_as_a_script_the_page_can_load_early(self, client):
        response = client.get("/i18n/terms.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")
        assert "max-age" in response.headers["cache-control"]
        body = response.text
        assert body.startswith("window.U2_TERMS = ") and body.endswith(";")
        terms = json.loads(body[len("window.U2_TERMS = "):-1])
        assert terms == english_terms()
        assert terms["obras civis"] == "Civil Works"

    def test_keys_are_already_normalized_the_way_the_page_normalizes(self):
        # i18n.js::termKey repete translation._norm; uma chave fora do padrão nunca casaria
        assert all(key == _norm(key) for key in english_terms())

    def test_returned_dictionary_is_a_copy(self):
        english_terms()["obras civis"] = "x"
        assert english_terms()["obras civis"] == "Civil Works"


class TestClickUpNames:
    def test_schedule_and_studio_activities_have_english_names(self):
        assert translate("Cura do Concreto", "en") == "Concrete Curing"
        assert translate("Regularização de Solo e Compactação", "en") == "Soil Grading and Compaction"
        assert translate("Torre entregue no site", "en") == "Tower delivered to site"
        assert translate("Instalação Unifi", "en") == "Unifi Installation"

    def test_portuguese_stays_untouched_in_portuguese(self):
        assert translate("Cura do Concreto", "pt") == "Cura do Concreto"

    def test_unknown_name_falls_back_to_the_original(self):
        assert translate("Nome que ninguém traduziu", "en") == "Nome que ninguém traduziu"


class TestAssistantLanguage:
    def test_english_interface_asks_for_an_english_answer(self):
        prompt = _system_prompt("en")
        assert prompt.startswith(_SYSTEM_PROMPT) and "in English" in prompt

    def test_portuguese_prompt_is_unchanged(self):
        assert _system_prompt("pt") == _SYSTEM_PROMPT

    def test_request_defaults_to_portuguese_and_rejects_other_languages(self):
        assert ChatRequest(message="oi").lang == "pt"
        assert ChatRequest(message="hi", lang="en").lang == "en"
        with pytest.raises(ValidationError):
            ChatRequest(message="hola", lang="es")
