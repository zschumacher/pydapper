# Agent Guide

This file is for coding agents working in pydapper. Keep changes narrow, prefer the
existing patterns, and report exactly which checks ran.

## Repository Shape

* `pydapper/` contains the runtime package. `main.py` exposes the public entry
  points, `commands.py` holds the shared command behavior, and each database
  backend has its own subpackage.
* `tests/` mirrors the supported backends. Core tests live in top-level test
  files and driver tests live under `tests/test_<backend>/`.
* `tests/test_suites/commands.py` contains shared behavior exercised by
  backend-specific tests. Reuse it when adding driver coverage.
* `tests/databases/` contains SQL fixtures for integration tests.
* `docs/` is the MkDocs source. Runnable docs examples live in `docs_src/` and
  are included from markdown with `markdown_include`.

## Development Setup

Use Poetry as the source of truth. Do not update `poetry.lock`, add
dependencies, or install optional extras unless the change needs them.

```console
poetry install
poetry install --with docs
```

The package currently declares Python `>=3.10,<4.0`, and CI runs Python
3.10-3.14. Do not introduce syntax or dependencies that break the oldest
supported runtime without updating project metadata and CI together.

## Core Commands

```console
poetry run pytest -m "core"
poetry run pytest -m "sqlite"
poetry run mypy pydapper
poetry run mypy tests/type_tests.py
poetry run black --check .
poetry run isort --check .
poetry run mkdocs build --strict
```

Useful Make targets:

```console
make fmt
make mypy
make test
make test-cov
make docs
```

`make test` runs the whole pytest suite. In narrow PRs, prefer marker-scoped
tests so you do not start optional database integrations accidentally.

## Driver-Specific Tests

Run driver tests only when the change touches that backend, shared command
behavior, DSN parsing, or docs that claim backend behavior. These tests may use
Docker, testcontainers, external images, emulator startup, or cloud/client
packages.

```console
poetry install -E psycopg2 -E psycopg -E aiopg
poetry run pytest -m "postgresql"

poetry install -E pymssql
poetry run pytest -m "mssql"

poetry install -E mysql-connector-python
poetry run pytest -m "mysql"

poetry install -E oracledb
poetry run pytest -m "oracle"

poetry install -E google-cloud-bigquery
poetry run pytest -m "bigquery"
```

For CI-equivalent coverage output, add:

```console
--cov=. --cov-branch -v --durations=25 --cov-report=xml
```

Do not run optional integrations blindly in documentation-only or narrowly
scoped PRs. State clearly when they were skipped.

## Coding Expectations

* Preserve the small DBAPI wrapper model. Avoid adding mandatory dependencies
  for optional database support.
* Keep sync and async behavior aligned where a backend supports both.
* Keep parameter handling safe for each DBAPI. Do not replace structured driver
  behavior with ad hoc SQL string formatting.
* Keep imports Black/isort compatible. isort is configured for one import per
  line and Black uses a 120 character line length.
* pydapper is typed (`pydapper/py.typed`). Public API changes should include
  type-test coverage in `tests/type_tests.py` when relevant.
* Treat behavior changes to `connect`, `connect_async`, `using`,
  `using_async`, command methods, DSN parsing, and parameter substitution as
  compatibility-sensitive.

## Docs Expectations

* Public documentation lives in `docs/`; runnable examples live in `docs_src/`.
* Add new docs pages to `mkdocs.yml` so they are discoverable.
* Prefer concise examples that can run as shown. Keep README-level installation
  and usage content out of development docs.
* Build docs with `poetry run mkdocs build --strict` when docs dependencies are
  already available.

## Roadmap And Review

The pydapper v1 roadmap is tracked in GitHub issues, especially
[#446](https://github.com/zschumacher/pydapper/issues/446). Do not fold broad
v1 API redesign into incidental bug fixes or documentation PRs unless the issue
explicitly calls for it.

PR titles should always use Conventional Commits format, for example
`docs: add agent development guide` or `fix: handle param alias conflict`.

In PR summaries, include:

* What changed and why.
* Which commands ran and their results.
* Which driver-specific tests were skipped and why.
* Any public API, type compatibility, docs, or optional-extra impact.

Repo-local Codex skills are not currently needed. Prefer this file and the
development docs unless a future workflow needs reusable, task-specific context
that would otherwise bloat normal agent prompts.
