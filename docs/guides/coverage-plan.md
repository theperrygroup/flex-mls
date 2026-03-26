# Coverage Plan

`flex_mls` now enforces `100%` line coverage and `100%` branch coverage. The
project configuration enables branch coverage for `flex_mls` and fails the test
run if total coverage drops below `100`.

## Coverage Commands

Run the repository defaults:

```bash
pytest
```

Inspect the detailed report explicitly:

```bash
pytest --cov=flex_mls --cov-report=term-missing
```

## Current Status

The latest local verification finished with `126` passing tests and `100%`
coverage across the package.

| Area | Primary tests | Status |
| --- | --- | --- |
| Shared HTTP transport | `tests/test_base_client.py` | `100%` |
| Authentication helpers | `tests/test_auth.py` | `100%` |
| Facade client | `tests/test_client.py` | `100%` |
| Shared models | `tests/test_models.py` | `100%` |
| Shared resource helpers | `tests/test_resources_helpers.py` | `100%` |
| Resource wrappers | `tests/test_properties.py`, `tests/test_openhouses.py`, `tests/test_members.py`, `tests/test_offices.py`, `tests/test_lookup.py`, `tests/test_media.py`, `tests/test_rooms.py`, `tests/test_units.py`, `tests/test_green_verification.py`, `tests/test_power_production.py` | `100%` |

## Maintenance Expectations

- Treat any coverage drop as a blocking regression.
- Add or update tests in the same change for every behavior change, bug fix, and
  public API addition.
- Cover branch behavior, not only happy paths. Prioritize validation failures,
  retry paths, refresh flows, fallback logic, and wrapper forwarding.
- Add a dedicated test file when introducing a new shared helper, client, or
  public module.
- Run `pytest` before considering Python work complete.

## Where To Extend First

When new code lands, start in the most relevant existing test file:

- Transport, retries, headers, error mapping, and paging:
  `tests/test_base_client.py`
- OAuth, OIDC, discovery, token exchange, and revocation:
  `tests/test_auth.py`
- Facade wiring, auth resolution, lazy clients, and OIDC helper methods:
  `tests/test_client.py`
- Shared query/page/replication helpers:
  `tests/test_models.py` and `tests/test_resources_helpers.py`
- Resource-specific endpoints and wrapper behavior:
  the matching `tests/test_<resource>.py` file

## Exit Criteria

- `pytest` passes locally
- Coverage stays at `100%` line coverage and `100%` branch coverage for
  `flex_mls`
- New modules ship with matching or clearly related test coverage in the same
  change
