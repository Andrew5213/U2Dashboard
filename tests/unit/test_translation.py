import pytest
from src.services.translation import translate, translate_task_row


@pytest.mark.parametrize("pt, expected_en", [
    ("Obras Civis", "Civil Works"),
    ("Obra Civil", "Civil Works"),
    ("Instalação de Blades", "Blade Installation"),
    ("Instalação de Servidores", "Server Installation"),
    ("Massa e Pintura", "Filler & Painting"),
    ("Limpeza da área", "Area Cleaning"),
    ("ESTUDIO CT7", "Studio CT7"),
    ("REDAÇÃO - Rádio Luanda", "Newsroom - Rádio Luanda"),
    ("SITE TRANSMITTER", "Transmitter Site"),
    ("complete", "Completed"),
])
def test_translate_known_terms(pt, expected_en):
    assert translate(pt, "en") == expected_en


def test_translate_is_case_and_accent_insensitive():
    assert translate("obras civis", "en") == "Civil Works"
    assert translate("OBRAS CIVIS", "en") == "Civil Works"


def test_translate_unknown_term_passes_through():
    assert translate("Termo Totalmente Novo Sem Traducao", "en") == "Termo Totalmente Novo Sem Traducao"


def test_translate_pt_lang_returns_original_unchanged():
    assert translate("Obras Civis", "pt") == "Obras Civis"


def test_translate_none_returns_empty_string():
    assert translate(None, "en") == ""


def test_translate_task_row_translates_name_list_folder_status():
    row = {
        "name": "Instalação de Servidores",
        "list_name": "ESTUDIO CT7",
        "folder_name": "Luanda",
        "status": "complete",
    }
    result = translate_task_row(row, "en")
    assert result["name"] == "Server Installation"
    assert result["list_name"] == "Studio CT7"
    assert result["status"] == "Completed"


def test_translate_task_row_pt_lang_returns_same_dict():
    row = {"name": "Obras Civis", "status": "complete"}
    assert translate_task_row(row, "pt") is row
