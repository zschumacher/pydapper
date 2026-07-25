"""The canonical conformance dataset and framework-owned SQL statement catalog.

The framework owns every query and DML statement so behavioral assertions never
depend on harness-authored SQL. Statements use pydapper's portable ``?name?``
placeholder syntax, so they run unchanged on every adapter; the harness owns only
dialect-specific concerns: creating and seeding the dataset, the (optionally
qualified) table name, identifier case, and narrow documented overrides through
``sql_overrides``.
"""

from types import MappingProxyType
from typing import Any
from typing import Mapping
from typing import Optional
from typing import Tuple

#: Column names of the canonical conformance table, in declaration order.
CONFORMANCE_COLUMNS: Tuple[str, ...] = ("id", "label", "score", "note")

#: The label value substituted for the empty string when a harness declares
#: ``supports_empty_strings = False`` (for example Oracle, which stores ``''`` as NULL).
FALLBACK_EMPTY_LABEL = "blank"

#: Canonical rows the harness must seed per case, as (id, label, score, note).
#: Row 2 exercises falsey values (empty label where supported, score 0); row 1
#: carries a SQL NULL note for the scalar NULL case.
CONFORMANCE_ROWS: Tuple[Tuple[Any, ...], ...] = (
    (1, "alpha", 10, None),
    (2, "", 0, "noted"),
    (3, "gamma", 10, "third"),
)

_STATEMENTS: Mapping[str, str] = MappingProxyType(
    {
        "select_literal": "SELECT 1",
        "select_all": "SELECT id, label, score, note FROM {table} ORDER BY id",
        "select_by_id": "SELECT id, label, score, note FROM {table} WHERE id = ?id?",
        "select_two": "SELECT id, label, score, note FROM {table} WHERE score = ?score? ORDER BY id",
        "select_id_label": "SELECT id, label FROM {table} WHERE id = ?id?",
        "select_duplicate_columns": "SELECT id, id FROM {table} WHERE id = ?id?",
        "select_repeated_placeholder": ("SELECT id, label, score, note FROM {table} WHERE id = ?id? AND ?id? = id"),
        "scalar_label": "SELECT label FROM {table} WHERE id = ?id?",
        "scalar_score": "SELECT score FROM {table} WHERE id = ?id?",
        "scalar_note": "SELECT note FROM {table} WHERE id = ?id?",
        "insert_row": "INSERT INTO {table} (id, label, score, note) VALUES (?id?, ?label?, ?score?, ?note?)",
        "update_label": "UPDATE {table} SET label = ?label? WHERE id = ?id?",
    }
)


def statement_ids() -> Tuple[str, ...]:
    """Return the stable identifiers of every framework-owned statement."""
    return tuple(sorted(_STATEMENTS))


def render_statement(
    statement_id: str,
    table_name: str,
    sql_overrides: Optional[Mapping[str, str]] = None,
) -> str:
    """Render one framework statement for a harness's table, honoring overrides.

    ``sql_overrides`` maps statement ids to replacement SQL (still using pydapper
    ``?name?`` placeholders and the ``{table}`` slot) for the narrow, documented
    situations where portable SQL is insufficient for a dialect.
    """
    if sql_overrides and statement_id in sql_overrides:
        template = sql_overrides[statement_id]
    else:
        try:
            template = _STATEMENTS[statement_id]
        except KeyError:
            raise KeyError(f"Unknown conformance statement id {statement_id!r}") from None
    return template.format(table=table_name)


def expected_column(name: str, column_case: str) -> str:
    """Map a canonical (lowercase) column name to the case the adapter reports."""
    return name.upper() if column_case == "upper" else name


def expected_row_dict(row: Tuple[Any, ...], column_case: str) -> Mapping[str, Any]:
    """Build the expected dict projection of one canonical row."""
    return {expected_column(name, column_case): value for name, value in zip(CONFORMANCE_COLUMNS, row)}


def seed_rows(supports_empty_strings: bool) -> Tuple[Tuple[Any, ...], ...]:
    """Return the canonical rows a harness must seed, honoring the empty-string knob."""
    if supports_empty_strings:
        return CONFORMANCE_ROWS
    adjusted = []
    for row in CONFORMANCE_ROWS:
        values = list(row)
        if values[1] == "":
            values[1] = FALLBACK_EMPTY_LABEL
        adjusted.append(tuple(values))
    return tuple(adjusted)
