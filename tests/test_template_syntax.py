"""Every Django tag must sit on one line.

Django's tokeniser is `{%.*?%}` with no DOTALL, so a tag broken across a newline
is not a tag at all — it becomes literal text, silently. There is no error at the
split; you find out somewhere else entirely, or never.

That is not hypothetical. A formatter run over `sandbox/templates` (199d0a3)
wrapped 41 tags across lines and took the whole portal down: `{% load careui i18n
%}` stopped loading, so every screen rendering a form died with
`Invalid filter: 'is_checkbox'` — nowhere near the actual damage. Others failed
quietly: `{% block step_title %}` never registered, and mangled `{% if %}`
conditions left nav items permanently inactive.

djLint passed the file both before and after, so this needs its own check.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

#: Django's own `tag_re`, but with DOTALL — so it finds precisely the spans
#: Django's tokeniser would fail to recognise.
TAG_SPANNING_LINES = re.compile(r"{%.*?%}", re.S)

TEMPLATES = Path(settings.APPS_DIR) / "templates"


def test_no_template_tag_is_split_across_lines():
    offenders = [
        f"{path.relative_to(TEMPLATES)}: {match.group(0)[:60]!r}"
        for path in sorted(TEMPLATES.rglob("*.html"))
        for match in TAG_SPANNING_LINES.finditer(path.read_text())
        if "\n" in match.group(0)
    ]

    assert not offenders, (
        "Template tags broken across a newline are not tags — Django renders "
        "them as text and reports nothing. Put each back on one line:\n  "
        + "\n  ".join(offenders)
    )


def test_every_template_compiles():
    """A tag that stopped being a tag often only shows up at parse time, and
    only on the screen that uses it. Parse them all instead."""
    from django.template.loader import get_template  # noqa: PLC0415

    failures = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        name = str(path.relative_to(TEMPLATES))
        try:
            get_template(name)
        except Exception as error:  # noqa: BLE001 — report every one, not the first
            failures.append(f"{name}: {error}")

    assert not failures, "Templates that do not compile:\n  " + "\n  ".join(failures)


#: The other two tokens Django's `tag_re` recognises, under the same rule.
OTHER_TOKENS_SPANNING_LINES = re.compile(r"{#.*?#}|{{.*?}}", re.S)


def test_no_template_comment_or_variable_is_split_across_lines():
    """`{# #}` and `{{ }}` are single-line for the same reason `{% %}` is.

    A wrapped comment is the quietest of the three: it is not a comment any
    more, so its prose renders into the page. The template still compiles and
    djLint still passes, so the first sign of it is paragraphs of explanation
    sitting in the sidebar — which is exactly how it reached a browser twice.
    """
    offenders = [
        f"{path.relative_to(TEMPLATES)}: {match.group(0)[:60]!r}"
        for path in sorted(TEMPLATES.rglob("*.html"))
        for match in OTHER_TOKENS_SPANNING_LINES.finditer(path.read_text())
        if "\n" in match.group(0)
    ]

    assert not offenders, (
        "A comment or variable broken across a newline is neither — Django "
        "renders it as text. Put each back on one line, or use "
        "{% comment %}...{% endcomment %} for prose:\n  " + "\n  ".join(offenders)
    )
