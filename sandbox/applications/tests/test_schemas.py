from __future__ import annotations

import pytest

from sandbox.applications.schemas import validate_payload
from sandbox.applications.schemas.sandbox import IntegrationIntent
from sandbox.applications.schemas.sandbox import SolutionType
from sandbox.applications.tests.factories import VALID_SANDBOX_DATA
from sandbox.utils.errors import DomainError


def _payload(**overrides):
    return {"schema_version": 1, "data": dict(VALID_SANDBOX_DATA, **overrides)}


def test_valid_sandbox_v1_payload_passes():
    validate_payload("SANDBOX", _payload())


def test_missing_schema_version_rejected():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", {"data": dict(VALID_SANDBOX_DATA)})


def test_missing_data_rejected():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", {"schema_version": 1})


def test_data_must_be_an_object():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", {"schema_version": 1, "data": "not-an-object"})


def test_unknown_kind_rejected():
    with pytest.raises(DomainError):
        validate_payload("NOT_A_KIND", _payload())


def test_unknown_schema_version_rejected():
    payload = _payload()
    payload["schema_version"] = 99
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", payload)


def test_solution_types_must_not_be_empty():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", _payload(solution_types=[]))


def test_solution_types_must_be_a_list():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", _payload(solution_types="HMIS"))


def test_solution_types_rejects_value_outside_the_choice_set():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", _payload(solution_types=["NOT_A_SOLUTION_TYPE"]))


def test_solution_types_rejects_an_integration_intent_value():
    # the exact confusion this schema was corrected for
    with pytest.raises(DomainError):
        validate_payload(
            "SANDBOX",
            _payload(solution_types=[IntegrationIntent.ABHA_M1.value]),
        )


def test_others_requires_the_free_text_companion():
    with pytest.raises(DomainError):
        validate_payload(
            "SANDBOX",
            _payload(solution_types=[SolutionType.OTHERS.value]),
        )


def test_others_accepted_with_the_free_text_companion():
    validate_payload(
        "SANDBOX",
        _payload(
            solution_types=[SolutionType.OTHERS.value],
            solution_type_others="Veterinary practice management",
        ),
    )


def test_integration_intents_must_not_be_empty():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", _payload(integration_intents=[]))


def test_integration_intents_rejects_value_outside_the_choice_set():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", _payload(integration_intents=["m1"]))


def test_payer_categories_is_optional():
    validate_payload("SANDBOX", _payload(payer_categories=[]))


def test_payer_categories_rejects_value_outside_the_choice_set():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", _payload(payer_categories=["Government"]))


def test_use_case_narrative_required():
    with pytest.raises(DomainError):
        validate_payload("SANDBOX", _payload(use_case_narrative="   "))
