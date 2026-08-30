# A2 — `users` + `organisations` models, membership, org-scoping mixin

> **Lane** A — Backend: domain & workflow · **Phase** V0.2 Apply & review · pair a senior with the junior here
> **Depends on** V0.1 (allauth user + login flows exist)
> **Unblocks** [A3](A3-applications-model.md), [C3](C3-route-gate-harness.md), every integrator-facing screen
> **Refs** [03-database.md §3.1](../03-database.md) · [01-backend.md §3.5](../01-backend.md) · [05-security.md §3.1](../05-security.md)

## In plain words

Two ideas, one ticket. First: _who you are_ (your user account) is separate from _which company you act for_ (the organisation); a membership row links them. Second, the portal's most important security tool: every page automatically limits its database queries to **your own organisation's records** — someone guessing another company's record URL just gets "not found", as if it didn't exist. Every screen built after this inherits that protection for free.

## Background

ABDM Sandbox v2 is a server-rendered Django monolith replacing the legacy portal, which crammed identity, organisation and application state into the ~75-column `SdLogin` table, used enumerable integer IDs in URLs, and leaked record existence via 403s. v2 splits identity (allauth user — already live from V0.1) from **tenancy** (organisation + membership), and makes org scoping an unforgettable queryset idiom: records outside your organisation resolve **404, never 403** (a 403 confirms existence of a guessable reference).

This mixin is the authz backbone of the whole portal — everything integrator-facing builds on it.

## What to build

### Deliverables

| #   | Deliverable                                                                        | Where                               |
| --- | ---------------------------------------------------------------------------------- | ----------------------------------- |
| 1   | `external_id` + `phone` on the user model + migration                              | `sandbox/users/models.py`           |
| 2   | `Organisation`, `Product` + `Membership` models, CHECKs, partial-unique migrations | `sandbox/organisations/models.py`   |
| 3   | `OrganisationScopedQuerySet.for_organisation()` manager                            | `sandbox/organisations/managers.py` |
| 4   | `OrganisationMixin` + session active-org selection                                 | `sandbox/organisations/mixins.py`   |
| 5   | Admin for organisation + membership                                                | `sandbox/organisations/admin.py`    |
| 6   | Tests: constraints, wrong-org → 404 (two-org fixture)                              | `sandbox/organisations/tests/`      |

### Models

`users_user` — extend the cookiecutter custom user (add only; email stays the login identity, unique/citext via allauth). **No Keycloak linkage on users** — portal logins are local; the integrator↔Keycloak relationship lives on the provisioning ledger ([B7](B7-provisioning-chain.md)):

| Field (add)         | Type           | Constraints / notes                                                         |
| ------------------- | -------------- | --------------------------------------------------------------------------- |
| `external_id`       | UUID           | unique, indexed, `default=uuid4`, non-editable (care base-model convention) |
| `name`              | char(255)      | already present in cookiecutter user                                        |
| `phone`             | char(20)       | optional; format validator with tests                                       |
| `email_verified_at` | datetime, null | stamped when allauth confirms the address                                   |
| `phone_verified_at` | datetime, null | stamped by the OTP service ([A4](A4-otp-service.md))                        |

`organisations_organisation` (extends the shared base model — `external_id`/`created_date`/`modified_date`/`deleted` not repeated below):

| Field                                  | Type                | Constraints / notes                                                                                |
| -------------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------- |
| `name`                                 | char(255)           |                                                                                                    |
| `slug`                                 | slug                | unique (`WHERE deleted = false`)                                                                   |
| `kind`                                 | char + CHECK        | `ORGANIZATION \| INDIVIDUAL` — which registration path was used                                    |
| `nature_of_entity`                     | char + CHECK, blank | legacy `natureOfEntity`: Company/Government/LLP/Partnership Firm/Proprietorship Firm/Society/Trust |
| `ownership`                            | char + CHECK, blank | legacy `typeOfApplication` ("Type of organization"): `GOVERNMENT \| PRIVATE`                       |
| `category`                             | char + CHECK, blank | legacy `selectCategory` — 13 values                                                                |
| `gst_number`                           | char(15), blank     | GSTIN, regex-validated                                                                             |
| `registered_in_india`                  | bool, null          | legacy `registerIndiaStatus`; null = never asked                                                   |
| `website`                              | URL                 | optional                                                                                           |
| address fields                         | char                | line1/line2/city/pincode — final list from the legacy SANDBOX form                                 |
| `lgd_state_code` / `lgd_district_code` | char(10)            | stored **by code**; LGD is external reference data with no table of ours ([A1](A1-catalog-app.md)) |
| `verification_state`                   | char + CHECK        | `PENDING \| VERIFIED` (v0 minimal)                                                                 |
| `verified_by`                          | FK → user, null     |                                                                                                    |
| `verified_at`                          | datetime, null      |                                                                                                    |

`organisations_membership`:

| Field          | Type              | Constraints / notes                                                                                                |
| -------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------ |
| `organisation` | FK → organisation | `on_delete=CASCADE`                                                                                                |
| `user`         | FK → user         | `on_delete=CASCADE`                                                                                                |
| `role`         | char + CHECK      | `OWNER \| DEVELOPER`                                                                                               |
| —              |                   | `UNIQUE (organisation, user) WHERE deleted = false` — partial, so a soft-deleted membership never blocks re-adding |

`organisations_product` — what actually gets certified. An organisation with two products needs two applications, two sets of credentials and two milestone tracks; legacy forced them to register twice as two "companies" because `SdLogin` carried a single `product_name`:

| Field          | Type              | Constraints / notes                                 |
| -------------- | ----------------- | --------------------------------------------------- |
| `organisation` | FK → organisation | `on_delete=PROTECT`                                 |
| `name`         | char(255)         | display name                                        |
| `slug`         | slug              | `UNIQUE (organisation, slug) WHERE deleted = false` |
| `description`  | text              | optional                                            |

### Org-scoping API (the authz backbone)

```python
# organisations/managers.py — mixed into every org-owned model (A3/A7 reuse it)
class OrganisationScopedQuerySet(models.QuerySet):
    def for_organisation(self, organisation: Organisation) -> Self: ...


# organisations/mixins.py — base for every integrator-facing view
class OrganisationMixin:
    """Resolves the active org from session membership; exposes self.organisation.
    All object lookups start from .for_organisation(...) — wrong-org objects 404."""
```

- Session active-org selection: auto-select when the user has one membership; minimal switcher when more.
- Admin for organisation + membership.

## Acceptance criteria

- [ ] Membership uniqueness and kind/verification CHECKs enforced + tested.
- [ ] A view under `OrganisationMixin` proves wrong-org → **404** with a two-org test fixture.
- [ ] UUID `external_id` used for all external lookups; integer PKs never appear in URLs.
- [ ] Route-gate matrix rows added for every URL this ticket ships ([C3](C3-route-gate-harness.md)).
- [ ] mypy/ruff clean; writes only in `services.py`/model methods, never views.

## Out of scope (deferred)

Org verification workflow UI · team invites · profile pages beyond allauth defaults (main plan P2/P5).
