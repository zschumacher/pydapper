import asyncio
from collections.abc import Awaitable
from inspect import isawaitable
from typing import Any
from typing import Generator
from typing import Generic
from typing import TypeVar
from typing import cast

_AwaitResultT = TypeVar("_AwaitResultT")
_EnterResultT = TypeVar("_EnterResultT")
_UNRESOLVED = object()


async def _await_if_needed(value: Any) -> Any:
    return await value if isawaitable(value) else value


class _AwaitableAsyncContextManager(Generic[_AwaitResultT, _EnterResultT]):
    """Wrap an awaitable resource for use with ``await`` or ``async with``."""

    __slots__ = ("_awaitable", "_resolution", "_obj", "_aexit", "_preserve_active_error")

    def __init__(self, awaitable: Awaitable[_AwaitResultT], *, preserve_active_error: bool = False):
        self._awaitable = awaitable
        self._resolution: asyncio.Future[_AwaitResultT] | object = _UNRESOLVED
        self._obj: _AwaitResultT | object = _UNRESOLVED
        self._aexit = None
        self._preserve_active_error = preserve_active_error

    async def _resolve(self) -> _AwaitResultT:
        if self._resolution is _UNRESOLVED:
            self._resolution = asyncio.ensure_future(self._awaitable)
        if self._obj is _UNRESOLVED:
            self._obj = await cast(asyncio.Future[_AwaitResultT], self._resolution)
        return cast(_AwaitResultT, self._obj)

    def __await__(self) -> Generator[Any, None, _AwaitResultT]:
        return self._resolve().__await__()

    async def __aenter__(self) -> _EnterResultT:
        obj = await self._resolve()
        enter = getattr(type(obj), "__aenter__", None)
        aexit = getattr(type(obj), "__aexit__", None)
        self._aexit = None
        if callable(enter) and callable(aexit):
            entered_obj = await _await_if_needed(enter(obj))
            self._aexit = aexit
            return cast(_EnterResultT, entered_obj)
        return cast(_EnterResultT, obj)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        obj = await self._resolve()
        try:
            if self._aexit is not None:
                return await _await_if_needed(self._aexit(obj, exc_type, exc_val, exc_tb))

            close = getattr(obj, "close", None)
            if callable(close):
                await _await_if_needed(close())
        except BaseException:
            if self._preserve_active_error and exc_type is not None:
                return False
            raise
