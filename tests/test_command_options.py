from dataclasses import FrozenInstanceError
from dataclasses import fields
from math import inf

import pytest

import pydapper
from pydapper.commands import Commands
from pydapper.commands import CommandsAsync
from pydapper.exceptions import UnsupportedFeatureError

pytestmark = pytest.mark.core


class NoCursorConnection:
    def cursor(self):
        raise AssertionError("cursor should not be allocated")


class OptionsCommands(Commands):
    @classmethod
    def connect(cls, parsed_dsn, **connect_kwargs):
        return cls(NoCursorConnection())


class OptionsCommandsAsync(CommandsAsync):
    @classmethod
    async def connect_async(cls, parsed_dsn, **connect_kwargs):
        return cls(NoCursorConnection())


def test_command_options_model():
    options = pydapper.CommandOptions()
    assert options == pydapper.CommandOptions()
    assert (
        repr(options)
        == "CommandOptions(timeout=None, command_kind=<CommandKind.TEXT: 'text'>, readonly=None, max_rows=None)"
    )
    assert options.command_kind is pydapper.CommandKind.TEXT
    assert [field.name for field in fields(options)] == ["timeout", "command_kind", "readonly", "max_rows"]
    assert hasattr(type(options), "__slots__")
    with pytest.raises(FrozenInstanceError):
        options.timeout = 1


@pytest.mark.parametrize("timeout", [0, -1, inf, float("nan"), True, "5"])
def test_invalid_timeout(timeout):
    with pytest.raises((TypeError, ValueError), match="timeout"):
        pydapper.CommandOptions(timeout=timeout)


@pytest.mark.parametrize("max_rows", [0, -1, 1.5, True, "5"])
def test_invalid_max_rows(max_rows):
    with pytest.raises((TypeError, ValueError), match="max_rows"):
        pydapper.CommandOptions(max_rows=max_rows)


def test_invalid_command_options_fields():
    with pytest.raises(TypeError, match="command_kind"):
        pydapper.CommandOptions(command_kind="text")
    with pytest.raises(TypeError, match="readonly"):
        pydapper.CommandOptions(readonly=1)


@pytest.mark.parametrize(
    "options",
    [
        pydapper.CommandOptions(timeout=1),
        pydapper.CommandOptions(command_kind=pydapper.CommandKind.STORED_PROCEDURE),
        pydapper.CommandOptions(readonly=True),
        pydapper.CommandOptions(max_rows=1),
    ],
)
def test_unsupported_options_fail_before_cursor_use(options):
    commands = OptionsCommands(NoCursorConnection())
    with pytest.raises(UnsupportedFeatureError):
        commands.execute("select 1", options=options)
    with pytest.raises(UnsupportedFeatureError):
        commands.execute("select 1", params=[], options=options)
    with pytest.raises(UnsupportedFeatureError):
        commands.query("select 1", buffered=False, options=options)


def test_default_options_are_supported():
    assert OptionsCommands(NoCursorConnection())._resolve_options(None) == pydapper.CommandOptions()
    assert (
        OptionsCommands(NoCursorConnection())._resolve_options(pydapper.CommandOptions()) == pydapper.CommandOptions()
    )


def test_non_options_value_fails_clearly():
    with pytest.raises(TypeError, match="options"):
        OptionsCommands(NoCursorConnection()).execute("select 1", options=object())


@pytest.mark.asyncio
async def test_async_unsupported_options_fail_before_cursor_use():
    with pytest.raises(UnsupportedFeatureError):
        await OptionsCommandsAsync(NoCursorConnection()).execute_async(
            "select 1", options=pydapper.CommandOptions(max_rows=1)
        )
