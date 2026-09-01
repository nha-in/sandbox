"""Every `ui-*` class a template names must exist in the built stylesheet.

Tailwind emits `@utility` rules on demand and says nothing about a class it has
no rule for, so a typo or a variant that careui never defined renders as plain
unstyled text. Three of these shipped before this test existed: `ui-btn--primary`
(no such variant — every filled call to action in the app was unstyled),
`ui-form-message` (form errors with no error colour) and a duplicate
`ui-section-title` that quietly overrode careui's own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STYLESHEET = REPO / "sandbox" / "static" / "css" / "tailwind.css"
TEMPLATES = REPO / "sandbox" / "templates"

#: `class="ui-badge--{{ variant }}"` leaves this prefix behind. The variants it
#: can actually produce are asserted in `sandbox/theme/tests/test_careui.py`.
INTERPOLATED = re.compile(r"^ui-[a-z-]*--$")

#: prose in template comments, not markup
NOT_MARKUP = {"ui-ext"}


def _defined() -> set[str]:
    return set(re.findall(r"\.(ui-[a-zA-Z0-9_-]+)", STYLESHEET.read_text()))


def _used() -> dict[str, set[str]]:
    used: dict[str, set[str]] = {}
    for template in TEMPLATES.rglob("*.html"):
        for name in re.findall(r"(ui-[a-zA-Z0-9_-]+)", template.read_text()):
            used.setdefault(name, set()).add(
                str(template.relative_to(TEMPLATES)),
            )
    return used


@pytest.mark.skipif(
    not STYLESHEET.exists(),
    reason="stylesheet is built by `manage.py tailwind build`",
)
def test_every_ui_class_a_template_names_has_a_rule():
    defined = _defined()
    missing = {
        name: sorted(where)
        for name, where in _used().items()
        if name not in defined
        and not INTERPOLATED.match(name)
        and name not in NOT_MARKUP
    }

    assert not missing, "ui-* classes with no rule in tailwind.css: " + "; ".join(
        f"{name} ({', '.join(where)})" for name, where in sorted(missing.items())
    )
