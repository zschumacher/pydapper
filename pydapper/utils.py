import importlib
from types import TracebackType
from typing import Any
from typing import Coroutine
from typing import Dict
from typing import Generator
from typing import Generic
from typing import List
from typing import Optional
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union

_TObj = TypeVar("_TObj")


def safe_getattr(obj: Any, key: str) -> Any:
    try:
        if isinstance(obj, dict):
            return obj[key]
        return getattr(obj, key)
    except AttributeError:
        raise AttributeError(f"Attribute {key!r} can not be accessed on {obj!r} or does not exist")
    except KeyError:
        raise KeyError(f"Key {key!r} can not be accessed on {obj!r} or does not exist")


def database_row_to_dict(col_names: List[str], row: Tuple[Any]) -> Dict[str, Any]:
    return dict(zip(col_names, row))


def serialize_dict_row(model: Any, row: Dict[str, Any]):
    if model == dict:
        return row
    return model(**row)


def get_col_names(cursor: Any) -> List[str]:
    return [i[0] for i in cursor.description]


def import_dbapi_module(dbapi_name: str):
    try:
        dbapi = importlib.import_module(dbapi_name)
    except ImportError:
        raise ImportError(f"Could not import module {dbapi_name}.  Try `pip install pydapper[{dbapi_name}]`")
    return dbapi


def import_module_obj_path(module_obj_path: str):
    if ":" not in module_obj_path:
        raise ValueError("Must specify object to import from module using colon ':'")
    module_name, obj_name = module_obj_path.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, obj_name)


class CoroutineContextManager(Coroutine[Any, Any, _TObj], Generic[_TObj]):  # pragma: no cover
    """Wrapper for coroutines to behave as a coroutine or a context manager"""

    __slots__ = ("_coro", "_obj")

    def __init__(
        self,
        coro: Coroutine[Any, Any, _TObj],
    ):
        self._coro = coro
        self._obj: Any = None

    def send(self, value: Any) -> "Any":
        return self._coro.send(value)

    def throw(  # type: ignore
        self,
        typ: Type[BaseException],
        val: Optional[Union[BaseException, object]] = None,
        tb: Optional[TracebackType] = None,
    ) -> Any:
        if val is None:
            return self._coro.throw(typ)
        if tb is None:
            return self._coro.throw(typ, val)
        return self._coro.throw(typ, val, tb)

    def close(self) -> None:
        self._coro.close()

    def __await__(self) -> Generator[Any, None, _TObj]:
        return self._coro.__await__()

    async def __aenter__(self) -> _TObj:
        self._obj = await self._coro
        assert self._obj
        return self._obj

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._obj.__aexit__(exc_type, exc_val, exc_tb)
