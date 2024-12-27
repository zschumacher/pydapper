from pydapper.parameters.named import NamedAdapter
from pydapper.parameters.qmark import QmarkAdapter
from pydapper.parameters.format import FormatAdapter
from pydapper.parameters.pyformat import PyformatAdapter
from pydapper.parameters.numeric import NumericAdapter
from pydapper.parameters.enums import ParamStyle
import pytest

@pytest.mark.parametrize(
    "adapter, query, params",
    [
        (NamedAdapter, "select * from tasks where id = :param_0 and owner = :param_1", {"param_0": 1, "param_1": "Zach"}),
        (QmarkAdapter, "select * from tasks where id = ? and owner = ?", (1, "Zach")),
        (FormatAdapter, "select * from tasks where id = %s and owner = %s", (1, "Zach")),
        (PyformatAdapter, "select * from tasks where id = %(param_0)s and owner = %(param_1)s", {"param_0": 1, "param_1": "Zach"}),
        (NumericAdapter, "select * from tasks where id = :1 and owner = :2", (1, "Zach")),
    ]
)
def test_from_numeric(adapter, query, params):
    source_query = "select * from tasks where id = :1 and owner = :2"
    source_params = (1, "Zach")
    adapter = adapter(source_query, source_params)
    assert adapter.query_style == ParamStyle.NUMERIC
    q, p = adapter.normalize()
    assert q == query
    assert p == params

@pytest.mark.parametrize(
    "adapter, query, params",
    [
        (NamedAdapter, "select * from tasks where id = :id and owner = :owner", {"id": 1, "owner": "Zach"}),
        (QmarkAdapter, "select * from tasks where id = ? and owner = ?", (1, "Zach")),
        (FormatAdapter, "select * from tasks where id = %s and owner = %s", (1, "Zach")),
        (PyformatAdapter, "select * from tasks where id = %(id)s and owner = %(owner)s", {"id": 1, "owner": "Zach"}),
        (NumericAdapter, "select * from tasks where id = :1 and owner = :2", (1, "Zach")),
    ]
)
def test_from_pyformat(adapter, query, params):
    source_query = "select * from tasks where id = %(id)s and owner = %(owner)s"
    source_params = {"id": 1, "owner": "Zach"}
    adapter = adapter(source_query, source_params)
    assert adapter.query_style == ParamStyle.PYFORMAT
    q, p = adapter.normalize()
    assert q == query
    assert p == params


@pytest.mark.parametrize(
    "adapter, query, params",
    [
        (NamedAdapter, "select * from tasks where id = :param_0 and owner = :param_1", {"param_0": 1, "param_1": "Zach"}),
        (QmarkAdapter, "select * from tasks where id = ? and owner = ?", (1, "Zach")),
        (FormatAdapter, "select * from tasks where id = %s and owner = %s", (1, "Zach")),
        (PyformatAdapter, "select * from tasks where id = %(param_0)s and owner = %(param_1)s", {"param_0": 1, "param_1": "Zach"}),
        (NumericAdapter, "select * from tasks where id = :1 and owner = :2", (1, "Zach")),
    ]
)
def test_from_format(adapter, query, params):
    source_query = "select * from tasks where id = %s and owner = %s"
    source_params = (1, "Zach")
    adapter = adapter(source_query, source_params)
    assert adapter.query_style == ParamStyle.FORMAT
    q, p = adapter.normalize()
    assert q == query
    assert p == params


@pytest.mark.parametrize(
    "adapter, query, params",
    [
        (NamedAdapter, "select * from tasks where id = :param_0 and owner = :param_1", {"param_0": 1, "param_1": "Zach"}),
        (QmarkAdapter, "select * from tasks where id = ? and owner = ?", (1, "Zach")),
        (FormatAdapter, "select * from tasks where id = %s and owner = %s", (1, "Zach")),
        (PyformatAdapter, "select * from tasks where id = %(param_0)s and owner = %(param_1)s", {"param_0": 1, "param_1": "Zach"}),
        (NumericAdapter, "select * from tasks where id = :1 and owner = :2", (1, "Zach")),
    ]
)
def test_from_qmark(adapter, query, params):
    source_query = "select * from tasks where id = ? and owner = ?"
    source_params = (1, "Zach")
    adapter = adapter(source_query, source_params)
    assert adapter.query_style == ParamStyle.QMARK
    q, p = adapter.normalize()
    assert q == query
    assert p == params

@pytest.mark.parametrize(
    "adapter, query, params",
    [
        (NamedAdapter, "select * from tasks where id = :id and owner = :owner", {"id": 1, "owner": "Zach"}),
        (QmarkAdapter, "select * from tasks where id = ? and owner = ?", (1, "Zach")),
        (FormatAdapter, "select * from tasks where id = %s and owner = %s", (1, "Zach")),
        (PyformatAdapter, "select * from tasks where id = %(id)s and owner = %(owner)s", {"id": 1, "owner": "Zach"}),
        (NumericAdapter, "select * from tasks where id = :1 and owner = :2", (1, "Zach")),
    ]
)
def test_from_named(adapter, query, params):
    source_query = "select * from tasks where id = :id and owner = :owner"
    source_params = {"id": 1, "owner": "Zach"}
    adapter = adapter(source_query, source_params)
    assert adapter.query_style == ParamStyle.NAMED
    q, p = adapter.normalize()
    assert q == query
    assert p == params

