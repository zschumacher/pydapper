import re
import typing
from abc import ABC
from abc import abstractmethod
from contextlib import ExitStack
from contextlib import contextmanager
from functools import cached_property
from re import Match
from typing import TYPE_CHECKING
from typing import Any
from typing import AsyncGenerator
from typing import Callable
from typing import Dict
from typing import Generator
from typing import List
from typing import Literal
from typing import Optional
from typing import Tuple
from typing import Type
from typing import TypeVar
from typing import Union
from typing import cast
from typing import overload

from coro_context_manager import CoroContextManager

from .exceptions import MoreThanOneResultException
from .exceptions import NoResultException
from .utils import database_row_to_dict
from .utils import get_col_names
from .utils import safe_getattr
from .utils import serialize_dict_row

if TYPE_CHECKING:
    from .dsn_parser import PydapperParseResult
    from .types import AsyncConnectionType
    from .types import AsyncCursorType
    from .types import ConnectionType
    from .types import CursorType
    from .types import ListParamType
    from .types import ParamType

    _T = TypeVar("_T")
    _Default = TypeVar("_Default")


class BaseSqlParamHandler(ABC):
    _PARAM_REGEX = "\\?(.*?)\\?"

    def __init__(self, sql: str, param: Union["ParamType", "ListParamType"] = None):
        self._sql = sql
        self._param = param
        if isinstance(self._param, list):
            all_params_are_same_type = all(isinstance(param, type(self._param[0])) for param in self._param[1:])
            if not all_params_are_same_type:
                raise ValueError(f"All objects in params must be of type {type(self._param[0])}")

    @abstractmethod
    def get_param_placeholder(self, param_name: str) -> str: ...

    @cached_property
    def ordered_param_names(self) -> Tuple[str, ...]:
        matches = re.findall(BaseSqlParamHandler._PARAM_REGEX, self._sql)
        matches = cast(List[str], matches)
        return tuple(matches)

    @cached_property
    def ordered_param_values(self) -> Union[Tuple[Any, ...], List[Tuple[Any, ...]], Tuple]:
        if self._param:
            if isinstance(self._param, list):
                return [tuple(safe_getattr(p, name) for name in self.ordered_param_names) for p in self._param]

            return tuple(safe_getattr(self._param, name) for name in self.ordered_param_names)
        return tuple()

    @cached_property
    def prepared_sql(self) -> str:
        if self._param and len(self.ordered_param_names) > 0:
            pattern = re.compile("|".join(re.escape(f"?{name}?") for name in self.ordered_param_names))

            def sub_param_with_placeholder(m: Match) -> str:
                matched_placeholder = m.group(0)
                matched_param_name = matched_placeholder.strip("?")
                return self.get_param_placeholder(matched_param_name)

            return pattern.sub(sub_param_with_placeholder, self._sql)  # type: ignore
        return self._sql

    def execute(self, cursor: "CursorType") -> int:
        if isinstance(self.ordered_param_values, list):
            cursor.executemany(self.prepared_sql, self.ordered_param_values)
        elif self.ordered_param_values:
            cursor.execute(self.prepared_sql, self.ordered_param_values)
        else:
            cursor.execute(self.prepared_sql)

        return cursor.rowcount

    async def execute_async(self, cursor: "AsyncCursorType") -> int:
        if isinstance(self.ordered_param_values, list):
            await cursor.executemany(self.prepared_sql, self.ordered_param_values)
        else:
            await cursor.execute(self.prepared_sql, self.ordered_param_values)

        return cursor.rowcount


class DefaultSqlParamHandler(BaseSqlParamHandler):
    def get_param_placeholder(self, param_name: str) -> str:
        return "%s"


class BaseCommands(ABC):
    SqlParamHandler: Type[BaseSqlParamHandler] = DefaultSqlParamHandler


class Commands(BaseCommands, ABC):
    def __init__(self, connection: "ConnectionType"):
        self.connection = connection

    def __enter__(self) -> "Commands":
        if hasattr(self.connection, "__enter__"):
            self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self.connection, "__exit__"):
            return self.connection.__exit__(exc_type, exc_val, exc_tb)

    @classmethod
    @abstractmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands": ...

    @contextmanager
    def _cursor_context_proxy(self):
        """Not all dbapis implement the cursor as a context manager.  This function handles that polymorphism."""
        with ExitStack() as stack:
            try:
                yield stack.enter_context(self.cursor())  # type: ignore
            except (AttributeError, TypeError):
                yield self.cursor()

    def cursor(self, *args, **kwargs) -> "CursorType":
        return self.connection.cursor(*args, **kwargs)

    def execute(self, sql: str, param: Union["ParamType", "ListParamType"] = None) -> int:
        handler = self.SqlParamHandler(sql, param)
        with self._cursor_context_proxy() as cursor:
            rowcount = handler.execute(cursor)
        return rowcount

    def _buffered_query(
        self, handler: BaseSqlParamHandler, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> List["_T"]:
        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            data = cursor.fetchall()
            return [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]

    def _unbuffered_query(self, handler: BaseSqlParamHandler, model: "Type[_T]") -> Generator["_T", None, None]:
        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            while True:
                row = cursor.fetchone()
                if not row:
                    break
                yield serialize_dict_row(model, database_row_to_dict(headers, row))

    @overload
    def query(
        self,
        sql: str,
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
        *,
        buffered: "Literal[True]" = True,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def query(
        self, sql: str, model: Type[Dict] = dict, param: Optional["ParamType"] = ..., *, buffered: "Literal[False]"
    ) -> typing.Generator[Dict[str, Any], None, None]: ...

    @overload
    def query(
        self,
        sql: str,
        param: Optional["ParamType"] = ...,
        buffered: "Literal[True]" = True,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> List["_T"]: ...

    @overload
    def query(
        self,
        sql: str,
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        buffered: "Literal[False]",
    ) -> Generator["_T", None, None]: ...

    def query(self, sql, model=dict, param=None, buffered=True):
        handler = self.SqlParamHandler(sql, param)
        return self._buffered_query(handler, model) if buffered else self._unbuffered_query(handler, model)

    # endregion

    def query_multiple(
        self, queries: Tuple[str, ...], models: Tuple[Any, ...] = None, param: Optional["ParamType"] = None
    ) -> Tuple[List[Any], ...]:
        """
        :todo use TypeVarTuple for the variadic types of models once the mypy support is better such that type checkers
              and hinters will be able to infer which model type you're working with.  Leaving this as is for now...
        """
        if models is None:
            models = tuple(dict for _ in queries)

        if len(queries) != len(models):
            raise ValueError("Number of queries must equal number of models")

        results = list()
        with self._cursor_context_proxy() as cursor:
            for query, model in zip(queries, models):
                handler = self.SqlParamHandler(query, param)
                handler.execute(cursor)
                headers = get_col_names(cursor)
                data = cursor.fetchall()

                if not data:
                    raise NoResultException(f"No results returned from query {query}")

                serialized_data = [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]
                results.append(serialized_data)

        return tuple(results)

    @overload
    def query_first(self, sql: str, model: Type[Dict] = dict, param: Optional["ParamType"] = ...) -> Dict[str, Any]: ...

    @overload
    def query_first(
        self, sql: str, param: Optional["ParamType"] = ..., *, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> "_T": ...

    def query_first(self, sql, model=dict, param=None):
        handler = self.SqlParamHandler(sql, param)

        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            row = cursor.fetchone()
            if not row:
                raise NoResultException("Query returned no results")
        return serialize_dict_row(model, database_row_to_dict(headers, row))

    @overload
    def query_first_or_default(
        self, sql: str, default: Callable[[], "_Default"], model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_first_or_default(
        self, sql: str, default: "_Default", model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_first_or_default(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> Union["_Default", "_T"]: ...

    @overload
    def query_first_or_default(
        self,
        sql: str,
        default: "_Default",
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> Union["_Default", "_T"]: ...

    def query_first_or_default(self, sql, default, model=dict, param=None):
        try:
            return self.query_first(sql, model=model, param=param)
        except NoResultException:
            return default() if callable(default) else default

    @overload
    def query_single(
        self, sql: str, model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Dict[str, Any]: ...

    @overload
    def query_single(
        self, sql: str, param: Optional["ParamType"] = ..., *, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> "_T": ...

    def query_single(self, sql, model=dict, param=None):
        handler = self.SqlParamHandler(sql, param)

        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            data = cursor.fetchall()

        num_records = len(data)
        if num_records == 0:
            raise NoResultException("Expected exactly one record, got zero")
        elif num_records > 1:
            raise MoreThanOneResultException(f"Expected exactly one record, got {num_records}")

        return serialize_dict_row(model, database_row_to_dict(headers, data[0]))

    @overload
    def query_single_or_default(
        self, sql: str, default: Callable[[], "_Default"], model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_single_or_default(
        self, sql: str, default: "_Default", model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_single_or_default(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> Union["_Default", "_T"]: ...

    @overload
    def query_single_or_default(
        self,
        sql: str,
        default: "_Default",
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> Union["_Default", "_T"]: ...

    def query_single_or_default(self, sql, default, model=dict, param=None):
        try:
            return self.query_single(sql, model=model, param=param)
        except NoResultException:
            return default() if callable(default) else default

    def execute_scalar(
        self,
        sql: str,
        param: "ParamType" = None,
    ) -> Any:
        handler = self.SqlParamHandler(sql, param)
        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            first_row = cursor.fetchone()
        if not first_row:
            raise NoResultException("Query returned no results")
        return first_row[0]


class CommandsAsync(BaseCommands, ABC):
    def __init__(self, connection: "AsyncConnectionType"):
        self.connection = connection

    async def __aenter__(self) -> "CommandsAsync":
        await self.connection.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.connection.__aexit__(exc_type, exc_val, exc_tb)

    @classmethod
    @abstractmethod
    async def connect_async(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "CommandsAsync": ...

    def cursor(self, *args, **kwargs) -> "CoroContextManager[AsyncCursorType]":
        return CoroContextManager(self.connection.cursor(*args, **kwargs))

    async def execute_async(self, sql: str, param: Union["ParamType", "ListParamType"] = None) -> int:
        handler = self.SqlParamHandler(sql, param)
        async with self.cursor() as cursor:
            return await handler.execute_async(cursor)

    async def _buffered_query(
        self, handler: BaseSqlParamHandler, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> List["_T"]:
        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            headers = get_col_names(cursor)
            data = await cursor.fetchall()
            return [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]

    async def _unbuffered_query(
        self, handler: BaseSqlParamHandler, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> AsyncGenerator["_T", None]:
        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            headers = get_col_names(cursor)
            while True:
                row = await cursor.fetchone()
                if not row:
                    break
                yield serialize_dict_row(model, database_row_to_dict(headers, row))

    @overload
    async def query_async(
        self,
        sql: str,
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
        *,
        buffered: "Literal[True]" = True,
    ) -> List[Dict[str, Any]]: ...

    @overload
    async def query_async(
        self, sql: str, model: Type[Dict] = dict, param: Optional["ParamType"] = ..., *, buffered: "Literal[False]"
    ) -> AsyncGenerator[Dict[str, Any], None]: ...

    @overload
    async def query_async(
        self,
        sql: str,
        param: Optional["ParamType"] = ...,
        buffered: "Literal[True]" = True,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> List["_T"]: ...

    @overload
    async def query_async(
        self,
        sql: str,
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        buffered: "Literal[False]",
    ) -> AsyncGenerator["_T", None]: ...

    async def query_async(self, sql, model=dict, param=None, buffered=True):
        handler = self.SqlParamHandler(sql, param)
        if buffered:
            records = await self._buffered_query(handler, model)
            return records
        return self._unbuffered_query(handler, model)

    async def query_multiple_async(
        self, queries: Tuple[str, ...], models: Tuple[Any, ...] = None, param: Optional["ParamType"] = None
    ) -> Tuple[List[Any], ...]:
        """
        :todo use TypeVarTuple for the variadic types of models once the mypy support is better such that type checkers
              and hinters will be able to infer which model type you're working with.  Leaving this as is for now...
        """
        if models is None:
            models = cast(Tuple[dict], tuple(dict for _ in queries))

        if len(queries) != len(models):
            raise ValueError("Number of queries must equal number of models")

        results = list()
        async with self.cursor() as cursor:
            for query, model in zip(queries, models):
                handler = self.SqlParamHandler(query, param)
                await handler.execute_async(cursor)
                headers = get_col_names(cursor)
                data = await cursor.fetchall()

                if not data:
                    raise NoResultException(f"No results returned from query {query}")

                serialized_data = [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]
                results.append(serialized_data)

        return cast(Tuple[List[Any]], tuple(results))

    @overload
    async def query_first_async(
        self, sql: str, model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Dict[str, Any]: ...

    @overload
    async def query_first_async(
        self, sql: str, param: Optional["ParamType"] = ..., *, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> "_T": ...

    async def query_first_async(self, sql, model=dict, param=None):
        handler = self.SqlParamHandler(sql, param)

        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            headers = get_col_names(cursor)
            row = await cursor.fetchone()
            if not row:
                raise NoResultException("Query returned no results")
        return serialize_dict_row(model, database_row_to_dict(headers, row))

    @overload
    async def query_first_or_default_async(
        self, sql: str, default: Callable[[], "_Default"], model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_first_or_default_async(
        self, sql: str, default: "_Default", model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_first_or_default_async(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> Union["_Default", "_T"]: ...

    @overload
    async def query_first_or_default_async(
        self,
        sql: str,
        default: "_Default",
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> Union["_Default", "_T"]: ...

    async def query_first_or_default_async(self, sql, default, model=dict, param=None):
        try:
            return await self.query_first_async(sql, model=model, param=param)
        except NoResultException:
            return default() if callable(default) else default

    @overload
    async def query_single_async(
        self, sql: str, model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Dict[str, Any]: ...

    @overload
    async def query_single_async(
        self, sql: str, param: Optional["ParamType"] = ..., *, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> "_T": ...

    async def query_single_async(self, sql, model=dict, param=None):
        handler = self.SqlParamHandler(sql, param)

        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            headers = get_col_names(cursor)
            data = await cursor.fetchall()

        num_records = len(data)
        if num_records == 0:
            raise NoResultException("Expected exactly one record, got zero")
        elif num_records > 1:
            raise MoreThanOneResultException(f"Expected exactly one record, got {num_records}")

        return serialize_dict_row(model, database_row_to_dict(headers, data[0]))

    @overload
    async def query_single_or_default_async(
        self, sql: str, default: Callable[[], "_Default"], model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_single_or_default_async(
        self, sql: str, default: "_Default", model: Type[Dict] = dict, param: Optional["ParamType"] = ...
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_single_or_default_async(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> Union["_Default", "_T"]: ...

    @overload
    async def query_single_or_default_async(
        self,
        sql: str,
        default: "_Default",
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> Union["_Default", "_T"]: ...

    async def query_single_or_default_async(self, sql, default, model=dict, param=None):
        try:
            return await self.query_single_async(sql, model=model, param=param)
        except NoResultException:
            return default() if callable(default) else default

    async def execute_scalar_async(
        self,
        sql: str,
        param: "ParamType" = None,
    ) -> Any:
        handler = self.SqlParamHandler(sql, param)
        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            first_row = await cursor.fetchone()
        if not first_row:
            raise NoResultException("Query returned no results")
        return first_row[0]
