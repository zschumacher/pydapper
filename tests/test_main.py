import pytest

from pydapper.main import CommandFactory
from pydapper.main import connect
from pydapper.main import register
from pydapper.main import using
from tests.dsn import MOCK_DSN
from tests.mocks import MockCommands
from tests.mocks import MockConnection


class TestCommandFactory:
    @pytest.fixture
    def register_mock_commands(self):
        register("tests")(MockCommands)
        yield
        CommandFactory.registry.pop("tests", None)

    def test_from_dsn(self, register_mock_commands):
        commands = CommandFactory.from_dsn(MOCK_DSN)
        assert isinstance(commands, MockCommands)

    def test_from_dsn_env_var(self, register_mock_commands, monkeypatch):
        monkeypatch.setenv("PYDAPPER_DSN", MOCK_DSN)
        commands = CommandFactory.from_dsn()
        assert isinstance(commands, MockCommands)

    def test_register(self, register_mock_commands):
        assert CommandFactory.registry["tests"] is MockCommands

    def test_from_connection(self, register_mock_commands):
        with using(MockConnection()) as commands:
            assert isinstance(commands, MockCommands)

    def test_from_connection_raises_when_missing_registry_entry(self):
        with pytest.raises(ValueError):
            using(MockConnection())


def test_register():
    assert register == CommandFactory.register


def test_using():
    assert using == CommandFactory.from_connection


def test_connect():
    assert connect == CommandFactory.from_dsn
