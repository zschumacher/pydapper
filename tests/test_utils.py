from contextlib import ExitStack
from types import SimpleNamespace

import pytest

from pydapper.utils import database_row_to_dict
from pydapper.utils import get_col_names
from pydapper.utils import import_dbapi_module
from pydapper.utils import import_module_obj_path
from pydapper.utils import safe_getattr
from tests.mocks import MockCursor


@pytest.mark.parametrize(
    "obj, key, expected",
    [
        ({"id": 1, "name": "Zach"}, "id", 1),
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
    assert database_row_to_dict(["id", "name"], (1, "Zach")) == {"id": 1, "name": "Zach"}


def test_get_col_names():
    cursor = MockCursor()
    assert get_col_names(cursor) == ["id", "name"]


@pytest.mark.parametrize("name", ["psycopg2", "sqlite3", "pymssql"])
def test_import_db_api_module(name: str):
    assert import_dbapi_module(name)


def test_import_db_api_module_missing_package_raises():
    with pytest.raises(ImportError):
        import_dbapi_module("some_fake_dbapi_package")


def test_import_module_obj_path():
    from pydapper.sqlite.sqlite3 import Sqlite3Commands

    assert import_module_obj_path("pydapper.sqlite.sqlite3:Sqlite3Commands") is Sqlite3Commands


def test_import_module_obj_raises_on_missing_obj():
    with pytest.raises(ValueError):
        import_module_obj_path("pydapper.sqlite.sqlite3")
