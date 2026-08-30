"""Server-side field validators for the enrolment wizard.

These replace the legacy `@NoSpecialCharacters` / `@Website` annotations from
`SandboxConstant.java`, whose patterns were unanchored — for example

    \\b([a-zA-ZÀ-ÿ]|[-,a-zA-Z0-9. '()]+[ ]*)+

matches any string containing *one* acceptable run, so `"<script>ok"` passed.
The rules here are anchored and say what they mean.

Deliberate departures from legacy:

* Website is left to Django's `URLValidator` (via `URLField`). The legacy regex
  `^(http|https)://[a-zA-Z0-9\\-.]+\\.[a-z]+$` rejected ports, paths and query
  strings — a bug that made integrators mangle real URLs, not a rule.
* Free prose (the use-case narrative) is **not** character-restricted. Legacy
  applied the no-special-characters rule to prose fields, which is why the
  legacy form rejected ordinary sentences. Autoescaping, not input filtering,
  is what keeps rendered output safe.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Letters, digits, spaces and the punctuation a real Indian address or company
# name needs. Anchored, so the whole value must comply.
PLAIN_TEXT_RE = re.compile(r"^[\w\-&,./'()# ]+$", re.UNICODE)

# 2-digit state code, 5-letter PAN prefix, 4 digits, entity letter, Z, checksum.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# Indian PIN codes never begin with 0.
PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")

_HAS_ALPHANUMERIC_RE = re.compile(r"[^\W_]", re.UNICODE)


def validate_plain_text(value: str) -> None:
    """Ordinary text: no angle brackets, no control characters, no markup."""
    if not PLAIN_TEXT_RE.match(value):
        message = _(
            "Use letters, numbers, spaces and - & , . / ' ( ) # only.",
        )
        raise ValidationError(message, code="invalid_plain_text")


def validate_name(value: str) -> None:
    """A name must carry at least one letter or digit, so ' -- ' is refused."""
    validate_plain_text(value)
    if not _HAS_ALPHANUMERIC_RE.search(value):
        message = _("Must contain at least one letter or number.")
        raise ValidationError(message, code="no_alphanumeric")


def validate_gstin(value: str) -> None:
    if not GSTIN_RE.match(value.upper()):
        message = _("Enter a 15-character GSTIN, for example 29ABCDE1234F1Z5.")
        raise ValidationError(message, code="invalid_gstin")


def validate_pincode(value: str) -> None:
    if not PINCODE_RE.match(value):
        message = _("Enter a 6-digit PIN code.")
        raise ValidationError(message, code="invalid_pincode")
