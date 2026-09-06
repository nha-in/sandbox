"""Collection gate for the cross-cutting tests, during the plan-14 port.

The actor fixtures that used to live here defined the route-gate matrix against
`sandbox/applications/`, which step 1 deleted. Plan 12 §8.1 names this
directory's debt: every module here is to be ported, rewritten or replaced, and
most land in steps 5 and 6. Until then they cannot import, so they are ignored
here rather than left to break collection for the whole suite.

The previous conftest, with the five-actor fixture set, is at 552692c^ and is
the reference for the step-5 rewrite.

`integrations/test_chains.py` has left this list: it was re-pointed at the
registry and `ProvisioningRun`, and it skips on its own when WireMock is absent.
While it sat here that skip could not fire, so CI's `WIREMOCK_REQUIRED=1` guard
was moot — "nobody started the container" and "the exit evidence passed" looked
identical.
"""

from __future__ import annotations

#: Awaiting rewrite in plan 12 §8 steps 5 and 6. Delete an entry as its module
#: is rewritten; the list reaching empty is what clears the debt.
collect_ignore = [
    # rewrite against the form registry and the experiences: / ohc: route names
    "test_route_gates.py",
    "test_enrollment_wizard.py",
    "test_navigation.py",
    "test_credentials_panel.py",
    "test_dashboard.py",
    # rewrite against the arriving theme (§4.1)
    "test_stylesheet.py",
    "test_template_syntax.py",
    # replace with experience's equivalent
    "test_merge_production_dotenvs_in_dotenv.py",
]
