"""Shared lifecycle helpers for resources pydapper creates and solely owns.

Besides the awaitable/async-context wrapper, this module owns the one cleanup-discard
policy used by both the sync cursor lifecycle in ``commands`` and the async wrapper
below, so the two halves cannot drift apart.
"""

import asyncio
import logging
from collections.abc import Awaitable
from inspect import isawaitable
from typing import Any
from typing import Generator
from typing import Generic
from typing import TypeVar
from typing import cast

logger = logging.getLogger(__name__)

_AwaitResultT = TypeVar("_AwaitResultT")
_EnterResultT = TypeVar("_EnterResultT")
_UNRESOLVED = object()
_DISCARDED_RESOLUTION_MESSAGE = (
    "the resource this wrapper acquired was closed when the only task awaiting it was cancelled after "
    "acquisition had already completed; the wrapper is spent and cannot resolve again"
)


async def _await_if_needed(value: Any) -> Any:
    return await value if isawaitable(value) else value


def _log_discarded_cleanup_error(cleanup_error: Exception) -> None:
    """Record a cleanup failure that is being discarded to preserve the active error.

    Cleaning up a pydapper-owned resource may not replace the error that is already
    propagating, so the cleanup exception is dropped rather than raised or chained --
    the active error must be re-raised as the same object. Dropping it silently makes a
    co-occurring driver failure undiagnosable, so it is recorded at ``DEBUG`` (off by
    default, never used for control flow) with its traceback attached.

    Only an ``Exception`` is ever discarded. A ``BaseException`` that is not an
    ``Exception`` -- ``KeyboardInterrupt``, ``SystemExit``, ``asyncio.CancelledError``, or
    ``GeneratorExit`` -- is not a resource problem: the first two are interpreter-level
    requests to stop and the last two are the runtime unwinding this code on purpose.
    Swallowing any of them is worse than losing the command error -- a dropped Ctrl-C is
    unrecoverable, and a dropped ``CancelledError`` breaks ``asyncio.timeout`` and task
    cancellation by making the task look like it ignored the cancel. Callers therefore
    deliberately let all of them propagate and beat the active error, which is not lost
    either: it survives as the propagating exception's implicit ``__context__``.
    """
    logger.debug(
        "Discarding %s raised while cleaning up a pydapper-owned resource",
        type(cleanup_error).__name__,
        exc_info=cleanup_error,
    )


def _close_quietly(obj: Any) -> None:
    """Best-effort ``close()`` of a pydapper-owned resource, discarding an ordinary failure."""
    try:
        close = getattr(obj, "close", None)
        if callable(close):
            close()
    except Exception as cleanup_error:
        _log_discarded_cleanup_error(cleanup_error)


async def _close_quietly_async(obj: Any) -> None:
    """Async twin of :func:`_close_quietly`; an awaitable ``close()`` result is awaited."""
    try:
        close = getattr(obj, "close", None)
        if callable(close):
            await _await_if_needed(close())
    except Exception as cleanup_error:
        _log_discarded_cleanup_error(cleanup_error)


class _AwaitableAsyncContextManager(Generic[_AwaitResultT, _EnterResultT]):
    """Wrap an awaitable resource for use with ``await`` or ``async with``."""

    __slots__ = ("_awaitable", "_resolution", "_obj", "_aexit", "_preserve_active_error", "_awaiting", "_discarded")

    def __init__(self, awaitable: Awaitable[_AwaitResultT], *, preserve_active_error: bool = False):
        self._awaitable = awaitable
        self._resolution: asyncio.Future[_AwaitResultT] | object = _UNRESOLVED
        self._obj: _AwaitResultT | object = _UNRESOLVED
        self._aexit = None
        self._preserve_active_error = preserve_active_error
        self._awaiting = 0
        self._discarded = False

    async def _resolve(self) -> _AwaitResultT:
        if self._discarded:
            raise RuntimeError(_DISCARDED_RESOLUTION_MESSAGE)
        if self._resolution is _UNRESOLVED:
            self._resolution = asyncio.ensure_future(self._awaitable)
        if self._obj is _UNRESOLVED:
            resolution = cast(asyncio.Future[_AwaitResultT], self._resolution)
            self._awaiting += 1
            try:
                self._obj = await resolution
            except BaseException:
                # acquisition runs as an independent future, so it can finish in the window between the
                # awaiting task being cancelled and this await being resumed with the CancelledError. The
                # object then exists with no owner and nothing left to close it -- see
                # _discard_abandoned_resolution. The cancellation is never suppressed; the close is
                # best-effort cleanup on the way out.
                self._awaiting -= 1
                await self._discard_abandoned_resolution(resolution)
                raise
            self._awaiting -= 1
        return cast(_AwaitResultT, self._obj)

    async def _discard_abandoned_resolution(self, resolution: "asyncio.Future[_AwaitResultT]") -> None:
        """Close a pydapper-owned resource whose acquisition completed with no awaiter left to own it.

        ``_resolve`` awaits an ``asyncio`` future, so the acquisition it drives is not cancelled by the
        awaiting task raising: cancelling a task whose awaited future has *already* completed cannot
        cancel that future, and the runtime instead throws ``CancelledError`` in at the resume point.
        The future then holds a live resource -- typically a cursor -- that the caller never received,
        because a raising ``await`` binds nothing, and that no ``__aexit__`` will ever reach, because a
        failed ``__aenter__`` is not exited. Closing it here is the only thing standing between that
        window and a leaked cursor for the lifetime of the connection.

        The resource is closed only when it demonstrably exists and is demonstrably unowned:

        * ``done() and not cancelled() and exception() is None`` -- otherwise ``result()`` would raise
          rather than hand back an object. A pending future has acquired nothing yet, a cancelled one had
          its acquisition cancelled with it, and a failed one never produced a resource to close.
        * no other awaiter -- ``_resolve`` may be awaited concurrently, and only the cancelled awaiter
          fails while the others still resume with the result. Closing a resource another task is about
          to be handed would trade this leak for a use-after-close, which is worse. ``_obj`` is checked
          for the same reason, since a concurrent awaiter may already have resumed and taken ownership.

        Closing makes the wrapper spent rather than merely unresolved: ``_resolution`` stays a completed
        future holding the now-closed object, so ``_discarded`` is set -- before the close is awaited --
        to stop a later ``_resolve`` from handing that object out as if it were healthy.
        """
        if self._awaiting or self._obj is not _UNRESOLVED:
            return
        if resolution.done() and not resolution.cancelled() and resolution.exception() is None:
            self._discarded = True
            await _close_quietly_async(resolution.result())

    def __await__(self) -> Generator[Any, None, _AwaitResultT]:
        return self._resolve().__await__()

    async def __aenter__(self) -> _EnterResultT:
        obj = await self._resolve()
        enter = getattr(type(obj), "__aenter__", None)
        aexit = getattr(type(obj), "__aexit__", None)
        self._aexit = None
        if callable(enter) and callable(aexit):
            try:
                entered_obj = await _await_if_needed(enter(obj))
            except BaseException:
                # the wrapped object was created by pydapper and is solely owned by it, so a failed
                # __aenter__ must not leak it: the object exists and still exposes close(). Standard
                # context-manager semantics -- a manager that fails to enter is not exited -- govern a
                # manager the caller supplied, which this never is. __aexit__ stays unbound, so the
                # object is never cleaned up twice, and the close failure loses to the entry error.
                await _close_quietly_async(obj)
                raise
            self._aexit = aexit
            return cast(_EnterResultT, entered_obj)
        return cast(_EnterResultT, obj)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        obj = await self._resolve()
        try:
            if self._aexit is not None:
                suppress = await _await_if_needed(self._aexit(obj, exc_type, exc_val, exc_tb))
                if self._preserve_active_error and exc_type is not None:
                    # a command-owned resource may not suppress the active command error, so a truthy
                    # native __aexit__ result is ignored
                    return False
                return suppress

            close = getattr(obj, "close", None)
            if callable(close):
                await _await_if_needed(close())
        except Exception as cleanup_error:
            if self._preserve_active_error and exc_type is not None:
                # only an ordinary exception is discarded here; a BaseException that is not an Exception
                # (KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit) is not caught at
                # all and propagates past the active error -- see _log_discarded_cleanup_error
                _log_discarded_cleanup_error(cleanup_error)
                return False
            raise
