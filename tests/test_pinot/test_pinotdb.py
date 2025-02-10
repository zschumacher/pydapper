import datetime

import pytest

from pydapper import connect
from pydapper import using
from pydapper.dsn_parser import PydapperParseResult
from pydapper.pinot import PinotDbCommands
from tests.test_suites.commands import ExecuteScalarTestSuite
from tests.test_suites.commands import QueryFirstOrDefaultTestSuite
from tests.test_suites.commands import QueryFirstTestSuite
from tests.test_suites.commands import QueryMultipleTestSuite
from tests.test_suites.commands import QuerySingleOrDefaultTestSuite
from tests.test_suites.commands import QuerySingleTestSuite
from tests.test_suites.commands import QueryTestSuite

pytestmark = pytest.mark.pinot


@pytest.fixture
def commands():
    import pinotdb

    conn = pinotdb.connect(host="localhost", port=8099)
    with PinotDbCommands(conn) as commands:
        yield commands


@pytest.mark.parametrize(
    "dsn, kwargs",
    [
        (PydapperParseResult("pinot://localhost"), {"scheme": "sup"}),
        (PydapperParseResult("pinot://localhost"), {"scheme": "https"}),
    ],
)
def test_connect_class_method_validation(dsn, kwargs):
    with pytest.raises(ValueError):
        with PinotDbCommands.connect(dsn, **kwargs):
            pass


@pytest.mark.parametrize("driver", ["pinot", "pinot+pinotdb"])
def test_connect(driver, server):
    dsn = f"{driver}://localhost"
    with connect(dsn) as commands:
        assert isinstance(commands, PinotDbCommands)


def test_using():
    import pinotdb

    with using(pinotdb.connect(host="localhost", port=8099)) as commands:
        assert isinstance(commands, PinotDbCommands)


@pytest.mark.vcr
class TestQuery(QueryTestSuite):

    def test_param(self, commands, task_table_name):
        # dates need explicit quotes when using pinotdb
        data = commands.query(
            f"select * from {task_table_name} where due_date = '?due_date?'",
            param={"due_date": datetime.date(2021, 12, 31)},
        )
        assert len(data) == 2
        assert all(isinstance(record, dict) for record in data)


@pytest.mark.vcr
class TestQueryFirst(QueryFirstTestSuite): ...


@pytest.mark.vcr
class TestQueryFirstOrDefault(QueryFirstOrDefaultTestSuite): ...


@pytest.mark.vcr
class TestQuerySingleOrDefault(QuerySingleOrDefaultTestSuite): ...


@pytest.mark.vcr
class TestQuerySingle(QuerySingleTestSuite): ...


@pytest.mark.vcr
class TestExecuteScalar(ExecuteScalarTestSuite): ...


@pytest.mark.vcr
class TestQueryMultiple(QueryMultipleTestSuite):

    def test_param(self, commands, owner_table_name, task_table_name):
        # dates need explicit quotes when using pinotdb
        owner, task = commands.query_multiple(
            (
                f"select * from {owner_table_name} where id = ?id?",
                f"select * from {task_table_name} where due_date = '?due_date?'",
            ),
            param={"id": 1, "due_date": datetime.date(2021, 12, 31)},
        )
        assert len(owner) == 1
        assert len(task) == 2
        assert isinstance(owner[0], dict)
        assert all(isinstance(record, dict) for record in task)
