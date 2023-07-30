import pytest

from pydapper.main import CommandFactory
from pydapper.main import connect
from pydapper.main import connect_async
from pydapper.main import register
from pydapper.main import register_async
from pydapper.main import using
from pydapper.main import using_async
from tests.mocks import MockAsyncCommands
from tests.mocks import MockAsyncConnection
from tests.mocks import MockCommands
from tests.mocks import MockConnection

DSN = "some_db+tests://localhost"

pytestmark = pytest.mark.core


class TestCommandFactory:
    @pytest.fixture
    def register_mock_commands(self):
        register("tests")(MockCommands)
        yield
        CommandFactory.sync_registry.pop("tests", None)

    @pytest.fixture
    def register_mock_async_commands(self):
        register_async("tests")(MockAsyncCommands)
        yield
        CommandFactory.async_registry.pop("tests", None)

    def test_from_dsn(self, register_mock_commands):
        commands = CommandFactory.from_dsn(DSN)
        assert isinstance(commands, MockCommands)

    @pytest.mark.asyncio
    async def test_from_dsn_async(self, register_mock_async_commands):
        commands = await CommandFactory.from_dsn_async(DSN)
        assert isinstance(commands, MockAsyncCommands)

    def test_from_dsn_env_var(self, register_mock_commands, monkeypatch):
        monkeypatch.setenv("PYDAPPER_DSN", DSN)
        commands = CommandFactory.from_dsn()
        assert isinstance(commands, MockCommands)

    @pytest.mark.asyncio
    async def test_from_dsn_async_env_var(self, register_mock_async_commands, monkeypatch):
        monkeypatch.setenv("PYDAPPER_DSN", DSN)
        commands = await CommandFactory.from_dsn_async()
        assert isinstance(commands, MockAsyncCommands)

    def test_register(self, register_mock_commands):
        assert CommandFactory.sync_registry["tests"] is MockCommands

    def test_register_async(self, register_mock_async_commands):
        assert CommandFactory.async_registry["tests"] is MockAsyncCommands

    def test_from_connection(self, register_mock_commands):
        with CommandFactory.from_connection(MockConnection()) as commands:
            assert isinstance(commands, MockCommands)

    @pytest.mark.asyncio
    async def test_from_connection_async(self, register_mock_async_commands):
        async with CommandFactory.from_connection_async(MockAsyncConnection()) as commands:
            assert isinstance(commands, MockAsyncCommands)

    def test_from_connection_raises_when_missing_registry_entry(self):
        with pytest.raises(ValueError):
            CommandFactory.from_connection(MockConnection())

    def test_from_connection_async_raises_when_missing_registry_entry(self):
        with pytest.raises(ValueError):
            CommandFactory.from_connection_async(MockAsyncConnection())


def test_register():
    assert register == CommandFactory.register


def test_register_async():
    assert register_async == CommandFactory.register_async


def test_using():
    assert using == CommandFactory.from_connection


def test_using_async():
    assert using_async == CommandFactory.from_connection_async


def test_connect():
    assert connect == CommandFactory.from_dsn


def test_connect_async():
    assert connect_async == CommandFactory.from_dsn_async
