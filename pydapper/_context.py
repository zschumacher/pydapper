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
    "the resource this wrapper acquired was closed once the caller could no longer reach it -- either the "
    "only task awaiting it was cancelled after acquisition had already completed, or its __aenter__ "
    "raised; the wrapper is spent and cannot resolve again"
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


def _owned_close(obj: Any) -> Any:
    """Resolve ``obj``'s callable ``close``, or ``None`` when it exposes none.

    A pydapper-owned resource is not required to have a ``close()``: ``connect_async()`` resolves to
    a ``CommandsAsync``, which has none. Every caller asks this one question both to decide whether a
    close can be attempted at all and to know afterwards whether anything was actually closed, so the
    two answers cannot disagree -- see :meth:`_AwaitableAsyncContextManager._discard_owned_object`.

    Attribute access can itself fail, since ``close`` may be a descriptor that raises. That is a
    cleanup failure like any other and may not replace the error already on its way out, so it is
    recorded and reported here as "nothing to close".
    """
    try:
        close = getattr(obj, "close", None)
    except Exception as cleanup_error:
        _log_discarded_cleanup_error(cleanup_error)
        return None
    return close if callable(close) else None


def _close_quietly(obj: Any) -> None:
    """Best-effort ``close()`` of a pydapper-owned resource, discarding an ordinary failure."""
    close = _owned_close(obj)
    if close is None:
        return
    try:
        close()
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

        What the close itself does to the wrapper is :meth:`_discard_owned_object`'s decision, shared
        with the other discard path.
        """
        if self._awaiting or self._obj is not _UNRESOLVED:
            return
        if resolution.done() and not resolution.cancelled() and resolution.exception() is None:
            await self._discard_owned_object(resolution.result())

    async def _discard_owned_object(self, obj: Any) -> None:
        """Close a pydapper-owned resource the caller can no longer reach, and spend the wrapper.

        The one discard policy for both paths that strand an already-acquired object -- an awaiter
        cancelled after acquisition completed, and an ``__aenter__`` that raised -- so the two cannot
        drift apart. The object is closed best-effort, a cleanup failure never replaces the error on
        its way out, and the wrapper is marked spent so a later ``_resolve`` cannot hand the closed
        object out as if it were healthy: ``_resolution`` stays a completed future still holding it.

        Being spent is tied to a close actually being attempted, because the two consequences only make
        sense together. A resource exposing no callable ``close()`` -- ``connect_async()`` resolves to a
        ``CommandsAsync``, which has none -- cannot be cleaned up here at all, and poisoning the wrapper
        anyway would put a still-open resource permanently out of reach behind a ``RuntimeError`` that
        claims it was closed. The wrapper therefore stays resolvable in that case and keeps handing the
        live object back, which is the only remaining way for the caller to clean it up.

        ``_discarded`` is set before the close is awaited: a ``close()`` that suspends would otherwise
        leave a window in which a newly arriving awaiter resolves and takes the object out mid-close.
        """
        close = _owned_close(obj)
        if close is None:
            return
        self._discarded = True
        try:
            await _await_if_needed(close())
        except Exception as cleanup_error:
            _log_discarded_cleanup_error(cleanup_error)

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
                # This strands an acquired object exactly as a cancelled awaiter does, so it takes the
                # same discard policy: once closed, the wrapper is spent and will not hand the closed
                # object to the next await or async with.
                await self._discard_owned_object(obj)
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
