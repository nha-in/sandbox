"""Reference-data selectors — never write through this module.

`state_choices`/`districts_for_state` are the stable contract P4's `LgdLookup`
adapter takes over (06-integrations.md §5); callers must not reach past them
into the dataset file or the Milestone queryset directly.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from sandbox.catalog.models import Milestone

LGD_DATASET_PATH = (
    Path(__file__).resolve().parent / "data" / "lgd_states_districts.json"
)


class _District(TypedDict):
    code: str
    name: str


class _State(TypedDict):
    code: str
    name: str
    districts: list[_District]


@lru_cache(maxsize=1)
def _lgd_dataset() -> list[_State]:
    payload = json.loads(LGD_DATASET_PATH.read_text())
    return payload["states"]


def state_choices() -> list[tuple[str, str]]:
    """Wizard state dropdown: (code, name) pairs, dataset order."""
    return [(state["code"], state["name"]) for state in _lgd_dataset()]


def districts_for_state(state_code: str) -> list[tuple[str, str]]:
    """Htmx dependent select (C4): districts for `state_code`, or `[]` if unknown."""
    for state in _lgd_dataset():
        if state["code"] == state_code:
            return [(d["code"], d["name"]) for d in state["districts"]]
    return []


def is_valid_state_code(state_code: str) -> bool:
    return any(code == state_code for code, _ in state_choices())


def is_valid_district_code(state_code: str, district_code: str) -> bool:
    return any(code == district_code for code, _ in districts_for_state(state_code))


def active_milestones() -> list[Milestone]:
    """Milestones page / A7 declarations: active, in display order."""
    return list(Milestone.objects.filter(is_active=True))
