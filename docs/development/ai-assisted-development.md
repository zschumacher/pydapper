# AI-assisted development

This page summarizes the checks and review expectations for AI-assisted changes
to pydapper. It is intentionally shorter than the root `AGENTS.md`; use that
file as the operating guide for coding agents.

## Scope changes narrowly

Most pydapper changes affect one of these areas:

* shared command behavior in `pydapper/commands.py`
* public entry points and DSN routing in `pydapper/main.py` and
  `pydapper/dsn_parser.py`
* one optional database backend under `pydapper/<backend>/`
* tests and fixtures under the matching `tests/test_<backend>/` and
  `tests/databases/` paths
* documentation under `docs/` with runnable snippets under `docs_src/`

Keep optional database dependencies optional. Avoid changing package metadata,
lock files, CI, or multiple backends unless the task requires it.

## Preferred checks

Run the smallest check set that covers the change:

```console
poetry run pytest -m "core"
poetry run pytest -m "sqlite"
poetry run mypy pydapper
poetry run mypy tests/type_tests.py
poetry run black --check .
poetry run isort --check .
poetry run mkdocs build --strict
```

Driver-specific checks should be explicit and justified:

```console
poetry run pytest -m "postgresql"
poetry run pytest -m "mssql"
poetry run pytest -m "mysql"
poetry run pytest -m "oracle"
poetry run pytest -m "bigquery"
```

The non-SQLite driver tests may need Poetry extras, Docker, testcontainers,
external images, emulators, or cloud/client packages. Do not run them blindly in
narrow PRs; say which ones were skipped and why.

## Compatibility notes

pydapper currently targets Python `>=3.10,<4.0`, with CI coverage for Python
3.10-3.14. Public command methods, connection helpers, DSN parsing, parameter
substitution, and optional extras are compatibility-sensitive. Keep type-test
coverage current for public typing behavior.

The pydapper v1 roadmap is tracked in GitHub issues, especially
[#446](https://github.com/zschumacher/pydapper/issues/446). Keep broad v1 API
work tied to those issues instead of mixing it into unrelated PRs.

## PR handoff

An AI-assisted PR should make review easy:

* summarize the behavior or docs change
* list commands run and outcomes
* list skipped optional driver checks
* call out public API, typing, docs, or compatibility impact
