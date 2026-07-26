"""Structural guard that every adapter-author seam on ``Commands`` has an async twin.

A seam added to one mode and forgotten in the other is invisible to behavior tests: no
first-party async adapter overrides the missing hook, so nothing fails until a third-party
async adapter needs it and discovers that async exception timing differs from sync. #541
requires matching sync/async first/single/scalar timing, so the pairing is asserted
structurally here -- a new sync seam without an ``_async`` twin, or an async seam with no
sync original, fails this file even when no behavior test covers it.

The seams are the protected ``_prepare_*`` preparation hooks and the ``_on_*`` drain hooks
that let an adapter react to an in-flight command error (an unread-result drain, for
example) before the error propagates and the cursor is cleaned up.
"""

import inspect

import pytest

from pydapper.command_options import CommandOptions
from pydapper.commands import Commands
from pydapper.commands import CommandsAsync
from tests.mocks import MockAsyncCommands
from tests.mocks import MockCommands

pytestmark = pytest.mark.core

_SEAM_PREFIXES = ("_on_", "_prepare_")

# spelled out rather than derived so that adding or removing a seam is a deliberate edit here
EXPECTED_SYNC_SEAMS = frozenset(
    {
        "_on_duplicate_columns",
        "_on_query_single_more_than_one_result",
        "_prepare_command",
        "_prepare_cursor",
    }
)


def _seam_names(command_class):
    return frozenset(
        name
        for name in dir(command_class)
        if name.startswith(_SEAM_PREFIXES) and inspect.isfunction(getattr(command_class, name))
    )


def test_sync_seam_inventory_is_the_expected_set():
    assert _seam_names(Commands) == EXPECTED_SYNC_SEAMS


def test_every_sync_seam_has_an_async_twin_and_no_async_seam_is_orphaned():
    assert _seam_names(CommandsAsync) == frozenset(f"{name}_async" for name in _seam_names(Commands))


def test_sync_seams_are_plain_functions_and_async_seams_are_coroutine_functions():
    for name in _seam_names(Commands):
        assert not inspect.iscoroutinefunction(getattr(Commands, name)), name
    for name in _seam_names(CommandsAsync):
        assert inspect.iscoroutinefunction(getattr(CommandsAsync, name)), name


def test_paired_seams_take_the_same_parameters():
    for name in _seam_names(Commands):
        sync_parameters = inspect.signature(getattr(Commands, name)).parameters
        async_parameters = inspect.signature(getattr(CommandsAsync, f"{name}_async")).parameters
        assert list(sync_parameters) == list(async_parameters), name
        assert [parameter.kind for parameter in sync_parameters.values()] == [
            parameter.kind for parameter in async_parameters.values()
        ], name


def _seam_arguments(parameters):
    """Build sentinel arguments for a seam from its signature, skipping ``self``.

    Every argument except ``options`` is a bare ``object()``: a default implementation that
    is not inert would touch it and raise ``AttributeError`` instead of returning ``None``.
    """
    positional = []
    keywords = {}
    for parameter in list(parameters.values())[1:]:
        value = CommandOptions() if parameter.name == "options" else object()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            keywords[parameter.name] = value
        else:
            positional.append(value)
    return positional, keywords


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(EXPECTED_SYNC_SEAMS))
async def test_both_modes_default_to_an_inert_no_op(name):
    # the base implementations must stay inert so an adapter that overrides neither mode gets no
    # behavior of its own, and the async default of a seam only sync adapters need stays harmless
    sync_seam = getattr(Commands, name)
    async_seam = getattr(CommandsAsync, f"{name}_async")
    positional, keywords = _seam_arguments(inspect.signature(sync_seam).parameters)

    assert sync_seam(MockCommands(object()), *positional, **keywords) is None
    assert await async_seam(MockAsyncCommands(object()), *positional, **keywords) is None
