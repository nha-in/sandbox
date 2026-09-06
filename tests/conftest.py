"""Collection gate for the cross-cutting tests, during the plan-14 port.

The actor fixtures that used to live here defined the route-gate matrix against
`sandbox/applications/`, which step 1 deleted. Plan 14 §1.1 gives every module
in this directory a disposition — port, rewrite, or replace — and most of them
land in steps 5 and 6. Until then they cannot import, so they are ignored here
rather than left to break collection for the whole suite.

The previous conftest, with the five-actor fixture set, is at 552692c^ and is
the reference for the step-5 rewrite.
"""

from __future__ import annotations

#: Awaiting their disposition in plan 14 §1.1. Delete an entry as its module is
#: rewritten; the list reaching empty is what finishes §1.1.
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
    # rewrite with the step-5 re-anchor onto Sandbox.status
    "integrations/test_chains.py",
]
