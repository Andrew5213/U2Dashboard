import pytest

from src.services.authorization_service import (
    AuthorizationError,
    build_summary,
    build_task_name,
    format_field_value,
    requester_email,
    validate_note,
)


class TestFormatFieldValue:
    def test_text_field(self):
        assert format_field_value({"type": "text", "value": "Trocar PA"}) == "Trocar PA"

    def test_missing_value_returns_empty(self):
        assert format_field_value({"type": "text"}) == ""

    def test_dropdown_by_orderindex(self):
        field = {
            "type": "drop_down",
            "value": 1,
            "type_config": {"options": [
                {"id": "a", "name": "Transmissor", "orderindex": 0},
                {"id": "b", "name": "Gerador", "orderindex": 1},
            ]},
        }
        assert format_field_value(field) == "Gerador"

    def test_dropdown_by_option_id(self):
        field = {
            "type": "drop_down",
            "value": "b",
            "type_config": {"options": [
                {"id": "a", "name": "Transmissor", "orderindex": 0},
                {"id": "b", "name": "Gerador", "orderindex": 1},
            ]},
        }
        assert format_field_value(field) == "Gerador"

    def test_dropdown_unknown_value_is_empty(self):
        field = {"type": "drop_down", "value": 9, "type_config": {"options": []}}
        assert format_field_value(field) == ""

    def test_date_epoch_ms_is_formatted(self):
        # 14/09/2026 14:30 UTC
        field = {"type": "date", "value": "1789396200000"}
        assert format_field_value(field) == "14/09/2026 14:30"

    def test_checkbox_true_and_false(self):
        assert format_field_value({"type": "checkbox", "value": "true"}) == "Sim"
        assert format_field_value({"type": "checkbox", "value": False}) == "Não"

    def test_users_field_uses_username(self):
        field = {"type": "users", "value": [{"username": "Eduardo", "email": "e@u2.ao"}]}
        assert format_field_value(field) == "Eduardo"

    def test_users_field_falls_back_to_email(self):
        field = {"type": "users", "value": [{"email": "e@u2.ao"}]}
        assert format_field_value(field) == "e@u2.ao"

    def test_number_field(self):
        assert format_field_value({"type": "number", "value": "3"}) == "3"


class TestBuildSummary:
    def test_only_requester_fields_with_value(self):
        task = {
            "custom_fields": [
                {"name": "Motivo", "type": "text", "value": "Trocar PA"},
                {"name": "Site / Estúdio", "type": "short_text", "value": "FM Namibe"},
                {"name": "Duração Estimada (h)", "type": "number"},
            ]
        }
        summary = build_summary(task)
        assert ("Motivo", "Trocar PA") in summary
        assert ("Site / Estúdio", "FM Namibe") in summary
        assert all(label != "Duração Estimada (h)" for label, _ in summary)

    def test_decision_fields_are_excluded(self):
        task = {
            "custom_fields": [
                {"name": "Decidido Por", "type": "short_text", "value": "Chefe"},
                {"name": "Observações da Decisão", "type": "text", "value": "ok"},
                {"name": "Data da Decisão", "type": "date", "value": "1789396200000"},
                {"name": "Motivo", "type": "text", "value": "Trocar PA"},
            ]
        }
        assert build_summary(task) == [("Motivo", "Trocar PA")]


class TestValidateNote:
    def test_reject_requires_note(self):
        with pytest.raises(AuthorizationError):
            validate_note("reject", "")

    def test_reject_requires_non_whitespace_note(self):
        with pytest.raises(AuthorizationError):
            validate_note("reject", "   ")

    def test_reject_with_note_is_trimmed(self):
        assert validate_note("reject", "  sem verba  ") == "sem verba"

    def test_approve_without_note_is_allowed(self):
        assert validate_note("approve", None) == ""


class TestSummaryOrder:
    def test_follows_reading_order_not_clickup_alphabetical(self):
        task = {"custom_fields": [
            {"name": "Motivo", "type": "text", "value": "Trocar PA"},
            {"name": "Equipamento", "type": "short_text", "value": "Transmissor"},
            {"name": "Solicitante", "type": "users", "value": [{"username": "Eduardo"}]},
        ]}
        assert [label for label, _ in build_summary(task)] == [
            "Solicitante", "Equipamento", "Motivo",
        ]

    def test_unknown_fields_go_last_alphabetically(self):
        task = {"custom_fields": [
            {"name": "Zebra", "type": "text", "value": "z"},
            {"name": "Alfa", "type": "text", "value": "a"},
            {"name": "Motivo", "type": "text", "value": "m"},
        ]}
        assert [label for label, _ in build_summary(task)] == ["Motivo", "Alfa", "Zebra"]


class TestRequesterEmail:
    def test_prefers_email_type_field(self):
        task = {"custom_fields": [
            {"name": "E-mail", "type": "email", "value": " tecnico@u2.ao "},
            {"name": "Solicitante", "type": "users", "value": [{"email": "outro@u2.ao"}]},
        ], "creator": {"email": "dono@u2.ao"}}
        assert requester_email(task) == "tecnico@u2.ao"

    def test_falls_back_to_text_field_named_email(self):
        task = {"custom_fields": [
            {"name": "Email de contato", "type": "short_text", "value": "tecnico@u2.ao"},
        ], "creator": {"email": "dono@u2.ao"}}
        assert requester_email(task) == "tecnico@u2.ao"

    def test_ignores_text_field_without_at_sign(self):
        task = {"custom_fields": [
            {"name": "E-mail", "type": "short_text", "value": "nao informado"},
        ], "creator": {"email": "dono@u2.ao"}}
        assert requester_email(task) == "dono@u2.ao"

    def test_still_reads_users_field(self):
        task = {"custom_fields": [
            {"name": "Solicitante", "type": "users", "value": [{"email": "tecnico@u2.ao"}]},
        ]}
        assert requester_email(task) == "tecnico@u2.ao"

    def test_falls_back_to_creator(self):
        task = {"custom_fields": [
            {"name": "Solicitante", "type": "short_text", "value": "João Manuel"},
        ], "creator": {"email": "dono@u2.ao"}}
        assert requester_email(task) == "dono@u2.ao"

    def test_returns_empty_when_nothing_available(self):
        assert requester_email({"custom_fields": []}) == ""


class TestFieldOrderSurvivesRenames:
    def test_duration_matches_by_prefix_regardless_of_unit(self):
        task = {"custom_fields": [
            {"name": "Motivo", "type": "text", "value": "m"},
            {"name": "Duração Estimada (min)", "type": "number", "value": "45"},
            {"name": "Solicitante", "type": "short_text", "value": "João"},
        ]}
        assert [label for label, _ in build_summary(task)] == [
            "Solicitante", "Duração Estimada (min)", "Motivo",
        ]

    def test_email_comes_right_after_requester(self):
        task = {"custom_fields": [
            {"name": "Província", "type": "short_text", "value": "NAMIBE"},
            {"name": "E-mail", "type": "email", "value": "a@b.ao"},
            {"name": "Solicitante", "type": "short_text", "value": "João"},
        ]}
        assert [label for label, _ in build_summary(task)] == [
            "Solicitante", "E-mail", "Província",
        ]


class TestBuildTaskName:
    def test_combines_equipment_and_site(self):
        task = {"custom_fields": [
            {"name": "Equipamento", "type": "short_text", "value": "Transmissor FM 5kW"},
            {"name": "Site / Estúdio", "type": "short_text", "value": "FM Namibe — Torre 1"},
        ]}
        assert build_task_name(task) == "Transmissor FM 5kW — FM Namibe — Torre 1"

    def test_works_with_only_one_of_them(self):
        task = {"custom_fields": [
            {"name": "Equipamento", "type": "short_text", "value": "Gerador"},
        ]}
        assert build_task_name(task) == "Gerador"

    def test_empty_when_nothing_to_name_with(self):
        task = {"custom_fields": [{"name": "Motivo", "type": "text", "value": "algo"}]}
        assert build_task_name(task) == ""

    def test_ignores_blank_values(self):
        task = {"custom_fields": [
            {"name": "Equipamento", "type": "short_text", "value": "   "},
            {"name": "Site / Estúdio", "type": "short_text", "value": "FM Namibe"},
        ]}
        assert build_task_name(task) == "FM Namibe"

    def test_long_free_text_is_shortened(self):
        task = {"custom_fields": [
            {"name": "Equipamento", "type": "short_text",
             "value": "Transmissor FM 5kW da sala técnica principal com módulo de potência"},
        ]}
        name = build_task_name(task)
        assert len(name) <= 45
        assert name.endswith("…")

    def test_reads_dropdown_equipment_too(self):
        task = {"custom_fields": [
            {"name": "Equipamento", "type": "drop_down", "value": 0,
             "type_config": {"options": [{"id": "a", "name": "Transmissor", "orderindex": 0}]}},
        ]}
        assert build_task_name(task) == "Transmissor"
