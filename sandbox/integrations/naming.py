"""Names we derive rather than receive.

Shared by an adapter and its fake, so both produce the same value. Kept out of
the per-system packages because the fakes must reach it and the anti-corruption
contract forbids anything that pulls domain code into `integrations.wso2`.
"""

from __future__ import annotations

#: How an application is named in WSO2. The name is what create-or-lookup matches
#: on, and what B7 persists as `public_ref`. WSO2 rejects a name with a slash or
#: space; the reference is the stable half, so a re-run finds the app it made
#: last time.
APP_NAME_TEMPLATE = "sbx-{reference}"
