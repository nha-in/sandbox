# The adapter resilience suite (B9)

Points the **real** adapters at a programmable HTTP server instead of a stub
transport, so B1's timeouts, retry counts and breaker thresholds are observed
rather than asserted about, and chain idempotency is proven from the request
journal rather than from our own ledger.

WireMock is the tool, not the point — it is here because it can stall a response
and sever a socket, which no cassette library does.

## Running it

```sh
docker compose -f docker-compose.local.yml --profile wiremock up -d wiremock
uv run pytest tests/integrations
```

WireMock is profiled, so an ordinary `just up` does not start it and this suite
**skips**. That is deliberate for local work and dangerous in CI, so the pipeline
sets `WIREMOCK_REQUIRED=1`, which turns the skip into a failure — otherwise
"nobody started the container" and "everything passes" look identical.

`WIREMOCK_URL` defaults to `http://localhost:8081` (8080 on the host belongs to
Keycloak). CI runs pytest inside the compose network and sets
`http://wiremock:8080`.

## What is here

| File | Proves |
| --- | --- |
| `test_faults.py` | Read timeouts are real and bounded; idempotent calls retry exactly to the limit and POSTs never do; the breaker opens, stops touching the network, and half-opens; severed sockets and non-JSON bodies become typed `AdapterError`s. |
| `test_chains.py` | A re-run chain issues no second create; a chain killed at the last step resumes without duplicating; teardown disables each resource once; no read ever rotates the Keycloak secret. |

## Why this is not the contract half of B9

The ticket asks for fixtures "seeded from real sandbox-tier responses, redacted".
We have access to none of the four systems — that is the open carry-over on B3-B6
— so the stubs here are shaped from the legacy Java source, exactly like the
`*_stub.py` transports in `sandbox/integrations/tests/`.

That makes them evidence of **our** behaviour and not of ABDM's protocol. The
distinction matters: a directory of hand-written mappings named `fixtures/` would
imply a recording nobody made. Every assertion in this suite is therefore about
something we control — how many requests we sent, which verb we used, how long we
waited — and none of them depend on a response shape being right.

The contract half is deferred past v0, and when it happens it will probably not
use WireMock at all: Keycloak and WSO2 both have real containers we can run
(neither needs NHA), and the two that genuinely need recordings are better served
by `vcrpy`/`pytest-recording`, where redaction is code rather than a manual copy
out of a container. See `plan/v0-tickets/B9-adapter-resilience-suite.md`.

## Adding contract coverage later

Deferred past v0, and the approach differs per system. Full reasoning on the
ticket; the short version:

| System | Approach | Blocked on |
| --- | --- | --- |
| Keycloak | Run the real container — `compose/local/keycloak` already does | nothing |
| WSO2 | Run the real container — `wso2/wso2am` is published | nothing |
| HIE-CM | Recorded cassettes | NHA access |
| Notification | Recorded cassettes | NHA access |

For the two needing recordings, use `vcrpy` / `pytest-recording` rather than
WireMock's record mode. The reason is redaction: `before_record_response` and
`filter_headers` strip bearer tokens and `consumerSecret` on the way to disk, so
a recording *cannot* be committed unredacted because somebody forgot. WireMock's
record mode leaves you copying mappings out of a container and redacting by hand,
and one careless paste puts a live credential in git history for good.
