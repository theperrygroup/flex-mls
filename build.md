## Python API Client Library Blueprint (Generic)

This document is a **concrete, implementation-level blueprint** for a Python API client library repository.
It is intentionally **API-agnostic** so it can be used as input to an AI system to generate a new library for any API.

The blueprint describes a repository that:

- **Packages cleanly** with `pyproject.toml`
- Provides a **single top-level client** that exposes **resource-specific sub-clients**
- Uses **`requests` + a shared BaseClient** for HTTP, retries, timeouts, and consistent error handling
- Is **fully typed**, uses **Google-style docstrings**, and ships type information (`py.typed`)
- Has **100% test coverage** with `pytest` + `responses` (unit tests) and optional integration tests
- Has **MkDocs + mkdocstrings** documentation with a predictable docs layout
- Has CI for **formatting, linting, typing, security scans, tests, builds, docs, and releases**

---

## Repository layout (exact shape)

Use a **single top-level Python package directory** (not `src/` layout). Keep endpoints grouped by domain.

```text
<repo_root>/
  <package_name>/                     # import package (ships py.typed)
    __init__.py                       # exports public API, sets __version__
    py.typed

    base_client.py                    # HTTP core: session, headers, retries, errors
    exceptions.py                     # exception hierarchy used everywhere
    client.py                         # the facade client (lazy-load sub-clients)

    enums.py                          # shared enums used across modules (query params, filters)
    models.py                         # dataclasses/enums for request/response types (optional but recommended)

    <domain_a>.py                     # one client per domain (e.g. UsersClient)
    <domain_b>.py                     # one client per domain (e.g. OrdersClient)
    <domain_c>.py                     # ...

  tests/
    __init__.py
    test_base_client.py               # request/response behavior, retries, error mapping
    test_client.py                    # facade client lazy-loading/config propagation
    test_models.py                    # dataclass/enums sanity + serialization patterns
    test_<domain_a>.py                # domain client tests (requests mocked)
    test_<domain_b>.py
    ...

  examples/
    <workflow_1>.py                   # runnable scripts demonstrating common workflows
    <workflow_2>.py
    ...

  docs/
    index.md
    getting-started/
      index.md
      installation.md
      authentication.md
      quickstart.md
    guides/
      index.md
      examples.md
      troubleshooting.md
    api/
      index.md
      <domain_a>.md
      <domain_b>.md
      ...
    reference/
      index.md
      data-types.md
      exceptions.md
      changelog.md
    includes/
      abbreviations.md
    requirements.txt                  # documentation build dependencies
    stylesheets/
    javascripts/

  .github/
    workflows/
      ci.yml                          # formatting/lint/type/security + tests + build
      unified-deployment.yml          # docs deploy + release automation
      dependabot.yml

  .flake8
  .gitignore
  LICENSE
  MANIFEST.in
  mkdocs.yml
  pyproject.toml
  requirements.txt                   # runtime deps (optional if you rely on pyproject only)
  requirements-dev.txt               # dev/test/docs deps (optional if you rely on extras)
  STYLE_GUIDE.md                     # project code style rules (docstrings + typing)
  README.md
```

---

## Packaging & dependencies (pyproject-first)

### `pyproject.toml` essentials

Use `setuptools` build backend and declare:

- **Name/version/metadata**
- **Runtime dependencies**: at minimum `requests`, `typing-extensions`
- **Optional extras**:
  - `dev`: pytest, coverage, mocks, formatters, linters, type checkers, security tools
  - `dotenv`: optional `.env` support via `python-dotenv` (opt-in at runtime)
- **Tool config**: black, isort, mypy, pytest, coverage, flake8, pydocstyle
- **Typed package marker**: install `py.typed` as package data

### Version source of truth

Keep versions consistent:

- `pyproject.toml` has `version = "X.Y.Z"`
- `<package_name>/__init__.py` has `__version__ = "X.Y.Z"`

CI should verify version consistency for releases (tag vs files).

---

## Core architecture (how the library is implemented)

### 1) `BaseClient` (transport + shared behavior)

`BaseClient` is the only place that knows “how to talk HTTP”.
Every domain client either:

- **inherits** from `BaseClient`, or
- **wraps** an instance of `BaseClient` (composition).

This blueprint uses **inheritance** for domain clients.

#### Responsibilities

- **API key sourcing**
  - Accept `api_key: Optional[str]`
  - If missing, read an environment variable: `<API_KEY_ENV_VAR>`
  - If still missing, raise `AuthenticationError`
- **Session management**
  - Create one `requests.Session()`
  - Set default headers once, e.g.:
    - `<API_KEY_HEADER_NAME>: <api_key>` (commonly `X-API-KEY`)
    - `Accept: application/json`
    - `Content-Type: application/json` (only safe for JSON requests)
- **Timeouts & retry config**
  - `timeout_seconds: float`
  - `max_retries: int`
  - `retry_backoff_seconds: float`
  - Each may be overridden by explicit args OR environment variables like:
    - `<PREFIX>_TIMEOUT_SECONDS`
    - `<PREFIX>_MAX_RETRIES`
    - `<PREFIX>_RETRY_BACKOFF_SECONDS`
  - Parse env vars defensively (invalid values fall back to defaults)
- **Single request entrypoint**
  - `_request(method, endpoint, json_data, data, files, params, timeout_seconds)`
  - Builds URL as: `f"{base_url}/{endpoint.lstrip('/')}"` to tolerate leading slashes
- **Multipart/file uploads**
  - If `files` is present, do **not** send `json=...`
  - Do **not** force `Content-Type: application/json` for multipart requests
  - Use `requests.request(...)` with explicit headers for the multipart call so requests sets boundary
- **Retries**
  - Retry only transient failures (typical retryable status codes: 500, 502, 503, 504)
  - Exponential backoff: `retry_backoff_seconds * (2**attempt)`
  - Also retry on `requests.exceptions.RequestException` up to `max_retries`
- **Response decoding**
  - For `204 No Content`, return `{}` (empty object)
  - Attempt `response.json()`; if it fails, fall back to `response.text`
- **Error mapping (HTTP status → exception type)**
  - 400 → `ValidationError`
  - 401 → `AuthenticationError`
  - 404 → `NotFoundError`
  - 429 → `RateLimitError`
  - 5xx → `ServerError`
  - else → `ApiError` (generic)
  - Store `status_code` and `response_data` on exceptions for debugging

#### Public HTTP helpers

Expose tiny wrappers:

- `get(endpoint, params=None, *, timeout_seconds=None)`
- `post(endpoint, json_data=None, data=None, files=None, *, timeout_seconds=None)`
- `put(...)`
- `patch(...)`
- `delete(endpoint, *, timeout_seconds=None)`

All should delegate to `_request`.

---

### 2) `exceptions.py` (uniform error vocabulary)

Provide a simple hierarchy:

- `ApiError(Exception)` base class with:
  - `message: str`
  - `status_code: Optional[int]`
  - `response_data: Optional[Dict[str, Any]]`
- Subclasses:
  - `AuthenticationError`
  - `ValidationError`
  - `NotFoundError`
  - `RateLimitError`
  - `ServerError`
  - `NetworkError`

Optional: add **domain-specific** errors that extend a generic class when you learn real-world constraints
(e.g., “wrong call sequence” or “invalid field name”), but keep them minimal and justified by real API behavior.

---

### 3) Domain clients (`<domain>.py`)

Each domain file contains:

- One main client class named `<DomainName>Client`
- Related enums/constants specific to that domain (only if not shared)
- Methods that correspond **1:1** with API endpoints

#### Base URL strategy (single vs multi-service APIs)

If your API is split across multiple services (different base URLs), each domain client:

- Accepts `base_url: Optional[str] = None`
- Sets a **service-default** base URL when `base_url` is None
- Calls `super().__init__(..., base_url=<service_default_or_override>, ...)`

If your API is single-service, the facade client can pass its base URL into every sub-client.

#### Method design rules

- **Naming**: snake_case, descriptive; align closely with endpoint semantics
- **Parameters**:
  - Prefer explicit function parameters for common query params
  - Use `Optional[...]` for optional params
  - For repeated query params, accept `List[...]`
  - For enum-like filters, accept `Union[Enum, str]` or `List[Union[Enum, str]]`
- **Query params normalization**:
  - Convert `Enum` values to `.value`
  - Convert `date`/`datetime` to ISO strings when the API expects it
- **Return types**:
  - Default: `Dict[str, Any]` or `List[Dict[str, Any]]`
  - If an endpoint returns polymorphic JSON (e.g., string OR list OR object), type it as `Any` or a narrow `Union[...]`
  - Where you know the shape is stable, return dataclasses/models instead of dicts (optional)
- **Robustness**:
  - If the upstream sometimes returns multiple shapes, implement defensive parsing with clear errors

#### Docstrings (required)

Every public class and method uses Google-style docstrings:

- `Args`, `Returns`, `Raises`
- Optional `Example:` with a short snippet

---

### 4) Facade client (`client.py`)

Provide one “main” client that users import most often: `<MainClientName>`.

#### Responsibilities

- Accept shared configuration once:
  - `api_key`, `base_url` (optional), `timeout_seconds`, `max_retries`, `retry_backoff_seconds`
  - `load_dotenv: bool = False` (optional convenience)
- Lazily instantiate sub-clients via `@property`:
  - `self._<domain>: Optional[<DomainClient>] = None`
  - On first access, create the sub-client and cache it
- Propagate transport config (timeouts/retries) to sub-clients
- For sub-clients that use a different service base URL:
  - Do **not** pass the facade’s base URL (let sub-client default)

This gives users a stable entrypoint and keeps imports clean:

- `<client>.<domain>.<method>(...)`

---

### 5) Public exports (`__init__.py`)

`<package_name>/__init__.py` should:

- Set `__version__`
- Export the main client and domain clients
- Export shared exceptions and common enums
- Optionally export key models/dataclasses
- Define `__all__` for a controlled public surface

---

## Data typing strategy (models & enums)

This blueprint uses **standard-library `dataclasses` + `Enum`** for optional structured typing.

### When to use dataclasses

- Stable request/response objects used in multiple places
- Complex nested objects where dicts become unreadable

### When to keep dicts

- Large or frequently changing payloads
- Endpoints with inconsistent/unreliable response shapes

### Serialization

If you use dataclasses, tests should confirm:

- `dataclasses.asdict()` works
- nested structures serialize correctly
- default factories are used for list fields (`field(default_factory=list)`)

---

## Testing (pytest + responses, 100% coverage)

### Tooling

- `pytest`
- `pytest-cov`
- `responses` for mocking HTTP calls
- `pytest-mock` for patching

### Test structure (what to test)

#### `test_base_client.py`

- init behavior:
  - API key from parameter
  - API key from environment
  - missing API key raises
  - timeout/retry env vars parsed + invalid values fall back to defaults
- URL joining behavior (leading slash vs none)
- response handling:
  - 200 dict
  - 200 list
  - 200 string JSON
  - 204 empty
  - invalid JSON handling
- error mapping for 400/401/404/429/5xx/other
- retry behavior on:
  - retryable 5xx status codes
  - request exceptions
- multipart/file upload path uses correct request mechanism and does not force JSON headers

#### `test_client.py`

- facade initializes with config
- sub-clients are **lazy-loaded** and cached
- shared config propagates (timeouts/retries)
- multi-service clients do not inherit the facade base URL when they shouldn’t

#### `test_<domain>.py`

- each method hits the correct path and query string
- enums/date conversions to expected wire format
- input validation rules (e.g., max list size) raise `ValidationError`
- response “shape fixes” behave as intended (wrapped list vs raw list, etc.)

---

## Documentation (MkDocs + mkdocstrings)

### Goals

- One page per domain under `docs/api/`
- A “Getting Started” section that shows installation and authentication
- A “Reference” section documenting exceptions, enums, and data types

### Build dependencies

Keep doc-only deps in `docs/requirements.txt`, typically:

- mkdocs
- mkdocs-material
- mkdocstrings[python]
- pymdown-extensions
- minify plugin

### API reference rendering

Use `mkdocstrings` configured for:

- `docstring_style: google`
- headings at level 2 (so pages can use `##` / `###` consistently)
- hide source by default

---

## CI/CD (what pipelines must do)

### CI workflow: code quality + tests + build

On push/PR:

- **Formatting**: black
- **Imports**: isort
- **Linting**: flake8
- **Typing**: mypy (strict)
- **Security**: bandit + dependency vulnerability scan
- **Tests**: pytest matrix across supported Python versions with coverage
- **Build**: `python -m build` and `twine check`

### Unified deployment workflow

Support two modes:

1. **Docs-only** deployment (e.g., on main branch changes to docs/config)
2. **Release deployment** (tag or manual input):
   - version bump (if manual)
   - run checks + tests
   - build package
   - publish to package index (via secret)
   - build docs and deploy to GitHub Pages
   - create a GitHub release with artifacts + generated changelog

---

## “Add a new endpoint” checklist (the exact mechanical steps)

1. **Pick the target domain module**
   - If it fits an existing resource group, add a method there.
   - If it’s a new resource group, create a new `<domain>.py` with `<DomainClient>`.
2. **Implement the method**
   - Add strongly typed parameters
   - Map to correct HTTP verb + path
   - Build query params dict and normalize enums/dates
   - Return `Dict[str, Any]`/`List[Dict[str, Any]]` (or models if stable)
3. **Add or reuse enums/models**
   - Shared enums → `enums.py`
   - Structured payload models → `models.py` (dataclasses)
4. **Expose it**
   - If using a facade client, ensure it has a property for this domain client
   - Update `__init__.py` exports (`__all__`) so users can import cleanly
5. **Write tests**
   - Mock the HTTP call with `responses`
   - Assert URL, method, query string, and returned payload
   - Add tests for parameter conversion and validation
6. **Update docs**
   - Add/extend the domain page under `docs/api/<domain>.md`
   - Ensure docstrings are complete so mkdocstrings renders usable API reference
7. **Run the full suite locally**
   - `pytest`
   - `black .`
   - `isort .`
   - `flake8 .`
   - `mypy <package_name>/ --strict`

---

## AI generation prompt (optional, copy/paste)

If you want an AI to generate a new library using this blueprint, provide:

- API base URL(s) (single-service or multi-service)
- Authentication scheme (header name, token type, refresh flows if any)
- Endpoint list (paths, methods, parameters, request/response examples)
- Error payload shape examples
- Rate limit policy and retry guidance
- Naming conventions for domains/resources

And instruct it to produce:

- The exact repository layout in this document
- A `BaseClient` with retries/timeouts/error mapping
- One domain client per resource group
- A facade client that lazy-loads sub-clients
- Tests with mocked HTTP calls and 100% coverage
- MkDocs docs configured with mkdocstrings
