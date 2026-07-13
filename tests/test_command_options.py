from dataclasses import FrozenInstanceError
from dataclasses import fields
from fractions import Fraction
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


class DerivedOptions(pydapper.CommandOptions):
    pass


class OverflowingInfiniteReal(Fraction):
    def __float__(self):
        raise OverflowError

    def __eq__(self, other):
        return inf == other

    def __lt__(self, other):
        return inf < other

    def __le__(self, other):
        return inf <= other

    def __gt__(self, other):
        return inf > other

    def __ge__(self, other):
        return inf >= other


class OverflowingFraction(Fraction):
    def __float__(self):
        raise OverflowError


class UnorderableFraction(Fraction):
    def __gt__(self, other):
        raise TypeError("comparison is not supported")


class LegacyDefaultCommands(OptionsCommands):
    def query_first(self, sql, model=dict, param=None, *, mapper=None):
        return "first"

    def query_single(self, sql, model=dict, param=None, *, mapper=None):
        return "single"


class LegacyDefaultCommandsAsync(OptionsCommandsAsync):
    async def query_first_async(self, sql, model=dict, param=None, *, mapper=None):
        return "first"

    async def query_single_async(self, sql, model=dict, param=None, *, mapper=None):
        return "single"


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


@pytest.mark.parametrize("timeout", [0, -1, inf, -inf, float("nan"), True, "5"])
def test_invalid_timeout(timeout):
    with pytest.raises((TypeError, ValueError), match="timeout"):
        pydapper.CommandOptions(timeout=timeout)


@pytest.mark.parametrize("timeout", [10**1000, Fraction(10**1000, 1)])
def test_arbitrarily_large_timeout_is_validated_as_supported_real(timeout):
    options = pydapper.CommandOptions(timeout=timeout)

    with pytest.raises(UnsupportedFeatureError, match="timeout"):
        OptionsCommands(NoCursorConnection()).execute("select 1", options=options)


@pytest.mark.parametrize("timeout", [-(10**1000), Fraction(-(10**1000), 1)])
def test_arbitrarily_large_negative_timeout_is_invalid(timeout):
    with pytest.raises(ValueError, match="timeout"):
        pydapper.CommandOptions(timeout=timeout)


def test_custom_infinite_real_with_overflowing_float_conversion_is_invalid():
    with pytest.raises(ValueError, match="timeout"):
        pydapper.CommandOptions(timeout=OverflowingInfiniteReal(1))


def test_custom_finite_real_with_overflowing_float_conversion_is_valid():
    options = pydapper.CommandOptions(timeout=OverflowingFraction(10**1000, 1))

    with pytest.raises(UnsupportedFeatureError, match="timeout"):
        OptionsCommands(NoCursorConnection()).execute("select 1", options=options)


def test_custom_real_with_failing_comparison_is_invalid():
    with pytest.raises(ValueError, match="timeout must be a positive finite number or None"):
        pydapper.CommandOptions(timeout=UnorderableFraction(1))


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


@pytest.mark.parametrize("options", [None, pydapper.CommandOptions(), DerivedOptions()])
def test_default_options_are_omitted_for_legacy_default_helper_overrides(options):
    commands = LegacyDefaultCommands(NoCursorConnection())

    assert commands.query_first_or_default("select 1", None, options=options) == "first"
    assert commands.query_single_or_default("select 1", None, options=options) == "single"


def test_unsupported_options_fail_before_legacy_default_helper_overrides():
    commands = LegacyDefaultCommands(NoCursorConnection())
    options = pydapper.CommandOptions(timeout=1)

    with pytest.raises(UnsupportedFeatureError, match="timeout"):
        commands.query_first_or_default("select 1", None, options=options)
    with pytest.raises(UnsupportedFeatureError, match="timeout"):
        commands.query_single_or_default("select 1", None, options=options)


def test_non_options_value_fails_clearly():
    with pytest.raises(TypeError, match="options"):
        OptionsCommands(NoCursorConnection()).execute("select 1", options=object())


@pytest.mark.asyncio
async def test_async_unsupported_options_fail_before_cursor_use():
    with pytest.raises(UnsupportedFeatureError):
        await OptionsCommandsAsync(NoCursorConnection()).execute_async(
            "select 1", options=pydapper.CommandOptions(max_rows=1)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [None, pydapper.CommandOptions(), DerivedOptions()])
async def test_default_options_are_omitted_for_legacy_async_default_helper_overrides(options):
    commands = LegacyDefaultCommandsAsync(NoCursorConnection())

    assert await commands.query_first_or_default_async("select 1", None, options=options) == "first"
    assert await commands.query_single_or_default_async("select 1", None, options=options) == "single"


@pytest.mark.asyncio
async def test_unsupported_options_fail_before_legacy_async_default_helper_overrides():
    commands = LegacyDefaultCommandsAsync(NoCursorConnection())
    options = pydapper.CommandOptions(timeout=1)

    with pytest.raises(UnsupportedFeatureError, match="timeout"):
        await commands.query_first_or_default_async("select 1", None, options=options)
    with pytest.raises(UnsupportedFeatureError, match="timeout"):
        await commands.query_single_or_default_async("select 1", None, options=options)
