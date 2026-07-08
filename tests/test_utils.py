from collections import UserDict
from contextlib import ExitStack
from types import SimpleNamespace

import pytest

from pydapper.exceptions import DuplicateColumnException
from pydapper.utils import database_row_to_dict
from pydapper.utils import get_col_names
from pydapper.utils import import_dbapi_module
from pydapper.utils import import_module_obj_path
from pydapper.utils import safe_getattr
from pydapper.utils import validate_no_duplicate_columns
from tests.mocks import MockCursor

pytestmark = pytest.mark.core


@pytest.mark.parametrize(
    "obj, key, expected",
    [
        ({"id": 1, "name": "Zach"}, "id", 1),
        (UserDict({"id": 1, "name": "Zach"}), "id", 1),
        (SimpleNamespace(id=1, name="Zach"), "id", 1),
        ({"id": 1}, "name", KeyError),
        (SimpleNamespace(id=1), "name", AttributeError),
    ],
)
def test_safe_getattr(obj, key, expected):
    with ExitStack() as stack:
        if not isinstance(expected, int) and issubclass(expected, Exception):
            stack.enter_context(pytest.raises(expected))
        assert safe_getattr(obj, key) == expected


def test_database_row_to_dict():
    row = database_row_to_dict(["id", "name"], (1, "Zach"))

    assert row == {"id": 1, "name": "Zach"}
    assert list(row) == ["id", "name"]


@pytest.mark.parametrize(
    "col_names, duplicate_columns, duplicate_indexes",
    [
        (["id", "id"], ("id",), (0, 1)),
        (["id", "name", "id"], ("id",), (0, 2)),
        (["id", "name", "id", "name"], ("id", "name"), (0, 1, 2, 3)),
        (["id", "name", "id", "id"], ("id",), (0, 2, 3)),
    ],
)
def test_validate_no_duplicate_columns_rejects_duplicate_columns(col_names, duplicate_columns, duplicate_indexes):
    with pytest.raises(DuplicateColumnException) as exc_info:
        validate_no_duplicate_columns(col_names)

    assert exc_info.value.columns == tuple(col_names)
    assert exc_info.value.duplicate_columns == duplicate_columns
    assert exc_info.value.duplicate_indexes == duplicate_indexes
    assert "Alias duplicate columns" in str(exc_info.value)


def test_validate_no_duplicate_columns_allows_case_distinct_column_names():
    validate_no_duplicate_columns(["id", "ID"])


def test_database_row_to_dict_allows_case_distinct_column_names():
    assert database_row_to_dict(["id", "ID"], (1, 2)) == {"id": 1, "ID": 2}


def test_database_row_to_dict_missing_keys_raise_normal_key_error():
    row = database_row_to_dict(["id"], (1,))

    with pytest.raises(KeyError):
        row["missing"]


def test_get_col_names():
    cursor = MockCursor()
    assert get_col_names(cursor) == ["id", "name"]


def test_import_db_api_module():
    assert import_dbapi_module("sqlite3")


def test_import_db_api_module_missing_package_raises():
    with pytest.raises(ImportError):
        import_dbapi_module("some_fake_dbapi_package")


def test_import_module_obj_path():
    from pydapper.sqlite.sqlite3 import Sqlite3Commands

    assert import_module_obj_path("pydapper.sqlite.sqlite3:Sqlite3Commands") is Sqlite3Commands


def test_import_module_obj_raises_on_missing_obj():
    with pytest.raises(ValueError):
        import_module_obj_path("pydapper.sqlite.sqlite3")
