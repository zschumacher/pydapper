import typing
from abc import ABC
from abc import abstractmethod
from collections.abc import Mapping
from contextlib import ExitStack
from contextlib import contextmanager
from dataclasses import is_dataclass
from functools import cached_property
from inspect import signature
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

from ._context import CoroContextManager
from ._sql_placeholders import PlaceholderSpan
from ._sql_placeholders import scan_placeholder_spans
from .exceptions import DuplicateColumnException
from .exceptions import InvalidParameterShapeException
from .exceptions import MissingParameterException
from .exceptions import MoreThanOneResultException
from .exceptions import NoResultException
from .utils import database_row_to_dict
from .utils import get_col_names
from .utils import serialize_dict_row
from .utils import validate_no_duplicate_columns

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


class _ParamAliasUnset:
    def __repr__(self) -> str:
        return "None"


_PARAM_ALIAS_UNSET = _ParamAliasUnset()


def _resolve_param_aliases(param=_PARAM_ALIAS_UNSET, params=_PARAM_ALIAS_UNSET):
    if param is not _PARAM_ALIAS_UNSET and params is not _PARAM_ALIAS_UNSET:
        raise ValueError("Pass either 'params' or 'param', not both.")

    if params is not _PARAM_ALIAS_UNSET:
        return params

    if param is not _PARAM_ALIAS_UNSET:
        return param

    return None


def _is_empty_executemany_params(param: Any) -> bool:
    return isinstance(param, list) and not param


def _raise_if_list_params_for_read(param: Any) -> None:
    if isinstance(param, list):
        raise InvalidParameterShapeException("Top-level list params are only supported by execute and execute_async.")


def _fetch_at_most_two_rows(cursor: "CursorType") -> Tuple[Any, ...]:
    fetchmany = getattr(cursor, "fetchmany", None)
    if callable(fetchmany):
        return tuple(fetchmany(2))

    first_row = cursor.fetchone()
    if first_row is None:
        return tuple()

    second_row = cursor.fetchone()
    if second_row is None:
        return (first_row,)

    return first_row, second_row


async def _fetch_at_most_two_rows_async(cursor: "AsyncCursorType") -> Tuple[Any, ...]:
    fetchmany = getattr(cursor, "fetchmany", None)
    if callable(fetchmany):
        return tuple(await fetchmany(2))

    first_row = await cursor.fetchone()
    if first_row is None:
        return tuple()

    second_row = await cursor.fetchone()
    if second_row is None:
        return (first_row,)

    return first_row, second_row


_INVALID_ATTRIBUTE_PARAM_TYPES = (
    str,
    bytes,
    bytearray,
    list,
    tuple,
    set,
    frozenset,
    range,
    memoryview,
)


def _is_attribute_param_record(param: Any) -> bool:
    if isinstance(param, type):
        return False
    if is_dataclass(param):
        return True
    if isinstance(param, _INVALID_ATTRIBUTE_PARAM_TYPES):
        return False
    return hasattr(param, "__dict__") or hasattr(type(param), "__slots__")


def _is_param_record(param: Any) -> bool:
    return isinstance(param, Mapping) or _is_attribute_param_record(param)


_UNINSPECTABLE_NO_ARG_DEFAULT_FACTORIES = (
    bool,
    bytearray,
    bytes,
    complex,
    dict,
    float,
    frozenset,
    int,
    object,
    set,
    str,
)


def _resolve_default_value(default):
    if not callable(default):
        return default

    try:
        signature(default).bind()
    except TypeError:
        return default
    except ValueError:
        if any(default is factory for factory in _UNINSPECTABLE_NO_ARG_DEFAULT_FACTORIES):
            return default()
        return default

    return default()


def _raise_invalid_param_record(param: Any, location: str) -> None:
    raise InvalidParameterShapeException(
        f"{location} must be a mapping or an object with attributes matching SQL placeholders; "
        f"got {type(param).__name__}."
    )


def _get_param_value(param: Any, param_name: str) -> Any:
    if isinstance(param, Mapping):
        try:
            return param[param_name]
        except KeyError:
            raise MissingParameterException(f"Missing SQL parameter {param_name!r}.") from None

    try:
        return getattr(param, param_name)
    except AttributeError:
        raise MissingParameterException(f"Missing SQL parameter {param_name!r}.") from None


class BaseSqlParamHandler(ABC):
    def __init__(self, sql: str, param: Union["ParamType", "ListParamType"] = None):
        self._sql = sql
        self._param = param
        self.ordered_param_values: Union[Tuple[Any, ...], List[Tuple[Any, ...]], Tuple] = (
            self._resolve_ordered_param_values()
        )

    @abstractmethod
    def get_param_placeholder(self, param_name: str) -> str: ...

    def get_param_value(self, param: Any, param_name: str) -> Any:
        return _get_param_value(param, param_name)

    def _resolve_ordered_param_values(self) -> Union[Tuple[Any, ...], List[Tuple[Any, ...]], Tuple]:
        if isinstance(self._param, list):
            return [
                self._ordered_param_values_for_record(param, f"params[{index}]")
                for index, param in enumerate(self._param)
            ]

        if self._param is None:
            if self.ordered_param_names:
                raise MissingParameterException(f"Missing SQL parameter {self.ordered_param_names[0]!r}.")
            return tuple()

        return self._ordered_param_values_for_record(self._param, "params")

    @cached_property
    def ordered_param_names(self) -> Tuple[str, ...]:
        return tuple(name for _, _, name in self._placeholder_spans)

    @cached_property
    def _placeholder_spans(self) -> Tuple[PlaceholderSpan, ...]:
        return scan_placeholder_spans(self._sql)

    def _ordered_param_values_for_record(self, param: Any, location: str) -> Tuple[Any, ...]:
        if not _is_param_record(param):
            _raise_invalid_param_record(param, location)

        return tuple(self.get_param_value(param, name) for name in self.ordered_param_names)

    @cached_property
    def prepared_sql(self) -> str:
        if self._placeholder_spans:
            prepared_sql_parts = []
            current_index = 0

            for start, end, name in self._placeholder_spans:
                prepared_sql_parts.append(self._sql[current_index:start])
                prepared_sql_parts.append(self.get_param_placeholder(name))
                current_index = end

            prepared_sql_parts.append(self._sql[current_index:])
            return "".join(prepared_sql_parts)
        return self._sql

    def execute(self, cursor: "CursorType") -> int:
        if isinstance(self.ordered_param_values, list):
            if not self.ordered_param_values:
                return 0
            cursor.executemany(self.prepared_sql, self.ordered_param_values)
        elif self.ordered_param_values:
            cursor.execute(self.prepared_sql, self.ordered_param_values)
        else:
            cursor.execute(self.prepared_sql)

        return cursor.rowcount

    async def execute_async(self, cursor: "AsyncCursorType") -> int:
        if isinstance(self.ordered_param_values, list):
            if not self.ordered_param_values:
                return 0
            await cursor.executemany(self.prepared_sql, self.ordered_param_values)
        elif self.ordered_param_values:
            await cursor.execute(self.prepared_sql, self.ordered_param_values)
        else:
            await cursor.execute(self.prepared_sql)

        return cursor.rowcount


class DefaultSqlParamHandler(BaseSqlParamHandler):
    def get_param_placeholder(self, param_name: str) -> str:
        return "%s"


class BaseCommands(ABC):
    SqlParamHandler: Type[BaseSqlParamHandler] = DefaultSqlParamHandler

    @staticmethod
    def _resolve_params(param=_PARAM_ALIAS_UNSET, params=_PARAM_ALIAS_UNSET):
        return _resolve_param_aliases(param, params)


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

    @overload
    def execute(self, sql: str, params: Union["ParamType", "ListParamType"] = None) -> int: ...

    @overload
    def execute(self, sql: str, *, param: Union["ParamType", "ListParamType"] = None) -> int: ...

    def execute(self, sql, params=_PARAM_ALIAS_UNSET, *, param=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        if _is_empty_executemany_params(resolved_params):
            return 0

        handler = self.SqlParamHandler(sql, resolved_params)
        with self._cursor_context_proxy() as cursor:
            rowcount = handler.execute(cursor)
        return rowcount

    def _buffered_query(
        self, handler: BaseSqlParamHandler, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> List["_T"]:
        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            try:
                validate_no_duplicate_columns(headers)
            except DuplicateColumnException:
                self._on_duplicate_columns(cursor)
                raise
            data = cursor.fetchall()
            return [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]

    def _unbuffered_query(self, handler: BaseSqlParamHandler, model: "Type[_T]") -> Generator["_T", None, None]:
        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            try:
                validate_no_duplicate_columns(headers)
            except DuplicateColumnException:
                self._on_duplicate_columns(cursor)
                raise

            row = cursor.fetchone()
            if row is None:
                return

            yield serialize_dict_row(model, database_row_to_dict(headers, row))

            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                yield serialize_dict_row(model, database_row_to_dict(headers, row))

    def _on_duplicate_columns(self, cursor: "CursorType") -> None:
        pass

    def _on_query_single_more_than_one_result(self, cursor: "CursorType") -> None:
        pass

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
        self,
        sql: str,
        model: Type[Dict] = dict,
        *,
        buffered: "Literal[True]" = True,
        params: Optional["ParamType"],
    ) -> List[Dict[str, Any]]: ...

    @overload
    def query(
        self,
        sql: str,
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
        *,
        buffered: "Literal[False]",
    ) -> typing.Generator[Dict[str, Any], None, None]: ...

    @overload
    def query(
        self,
        sql: str,
        model: Type[Dict] = dict,
        *,
        buffered: "Literal[False]",
        params: Optional["ParamType"],
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
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
        buffered: "Literal[True]" = True,
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

    @overload
    def query(
        self,
        sql: str,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        buffered: "Literal[False]",
        params: Optional["ParamType"],
    ) -> Generator["_T", None, None]: ...

    def query(self, sql, model=dict, param=_PARAM_ALIAS_UNSET, buffered=True, *, params=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        handler = self.SqlParamHandler(sql, resolved_params)
        return self._buffered_query(handler, model) if buffered else self._unbuffered_query(handler, model)

    # endregion

    @overload
    def query_multiple(
        self, queries: Tuple[str, ...], models: Tuple[Any, ...] = None, param: Optional["ParamType"] = None
    ) -> Tuple[List[Any], ...]: ...

    @overload
    def query_multiple(
        self, queries: Tuple[str, ...], models: Tuple[Any, ...] = None, *, params: Optional["ParamType"] = None
    ) -> Tuple[List[Any], ...]: ...

    def query_multiple(
        self,
        queries: Tuple[str, ...],
        models: Tuple[Any, ...] = None,
        param=_PARAM_ALIAS_UNSET,
        *,
        params=_PARAM_ALIAS_UNSET,
    ) -> Tuple[List[Any], ...]:
        """
        :todo use TypeVarTuple for the variadic types of models once the mypy support is better such that type checkers
              and hinters will be able to infer which model type you're working with.  Leaving this as is for now...
        """
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)

        if models is None:
            models = tuple(dict for _ in queries)

        if len(queries) != len(models):
            raise ValueError("Number of queries must equal number of models")

        results = list()
        with self._cursor_context_proxy() as cursor:
            for query, model in zip(queries, models):
                handler = self.SqlParamHandler(query, resolved_params)
                handler.execute(cursor)
                headers = get_col_names(cursor)
                data = cursor.fetchall()

                if not data:
                    raise NoResultException(f"No results returned from query {query}")

                validate_no_duplicate_columns(headers)
                serialized_data = [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]
                results.append(serialized_data)

        return tuple(results)

    @overload
    def query_first(
        self,
        sql: str,
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Dict[str, Any]: ...

    @overload
    def query_first(self, sql: str, model: Type[Dict] = dict, *, params: Optional["ParamType"]) -> Dict[str, Any]: ...

    @overload
    def query_first(
        self,
        sql: str,
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> "_T": ...

    @overload
    def query_first(
        self,
        sql: str,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
    ) -> "_T": ...

    def query_first(self, sql, model=dict, param=_PARAM_ALIAS_UNSET, *, params=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        handler = self.SqlParamHandler(sql, resolved_params)

        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            row = cursor.fetchone()
            if row is None:
                raise NoResultException("Query returned no results")
            validate_no_duplicate_columns(headers)
        return serialize_dict_row(model, database_row_to_dict(headers, row))

    @overload
    def query_first_or_default(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_first_or_default(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        model: Type[Dict] = dict,
        *,
        params: Optional["ParamType"],
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_first_or_default(
        self,
        sql: str,
        default: "_Default",
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_first_or_default(
        self,
        sql: str,
        default: "_Default",
        model: Type[Dict] = dict,
        *,
        params: Optional["ParamType"],
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
        default: Callable[[], "_Default"],
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
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

    @overload
    def query_first_or_default(
        self,
        sql: str,
        default: "_Default",
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
    ) -> Union["_Default", "_T"]: ...

    def query_first_or_default(self, sql, default, model=dict, param=_PARAM_ALIAS_UNSET, *, params=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        try:
            return self.query_first(sql, model=model, param=resolved_params)
        except NoResultException:
            return _resolve_default_value(default)

    @overload
    def query_single(
        self,
        sql: str,
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Dict[str, Any]: ...

    @overload
    def query_single(self, sql: str, model: Type[Dict] = dict, *, params: Optional["ParamType"]) -> Dict[str, Any]: ...

    @overload
    def query_single(
        self,
        sql: str,
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> "_T": ...

    @overload
    def query_single(
        self,
        sql: str,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
    ) -> "_T": ...

    def query_single(self, sql, model=dict, param=_PARAM_ALIAS_UNSET, *, params=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        handler = self.SqlParamHandler(sql, resolved_params)

        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            data = _fetch_at_most_two_rows(cursor)

            num_records = len(data)
            if num_records == 0:
                raise NoResultException("Expected exactly one record, got zero")
            elif num_records > 1:
                self._on_query_single_more_than_one_result(cursor)
                raise MoreThanOneResultException("Expected exactly one record, got at least two")

            validate_no_duplicate_columns(headers)

        return serialize_dict_row(model, database_row_to_dict(headers, data[0]))

    @overload
    def query_single_or_default(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_single_or_default(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        model: Type[Dict] = dict,
        *,
        params: Optional["ParamType"],
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_single_or_default(
        self,
        sql: str,
        default: "_Default",
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    def query_single_or_default(
        self,
        sql: str,
        default: "_Default",
        model: Type[Dict] = dict,
        *,
        params: Optional["ParamType"],
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
        default: Callable[[], "_Default"],
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
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

    @overload
    def query_single_or_default(
        self,
        sql: str,
        default: "_Default",
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
    ) -> Union["_Default", "_T"]: ...

    def query_single_or_default(self, sql, default, model=dict, param=_PARAM_ALIAS_UNSET, *, params=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        try:
            return self.query_single(sql, model=model, param=resolved_params)
        except NoResultException:
            return _resolve_default_value(default)

    @overload
    def execute_scalar(self, sql: str, params: Optional["ParamType"] = None) -> Any: ...

    @overload
    def execute_scalar(self, sql: str, *, param: Optional["ParamType"] = None) -> Any: ...

    def execute_scalar(self, sql, params=_PARAM_ALIAS_UNSET, *, param=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        handler = self.SqlParamHandler(sql, resolved_params)
        with self._cursor_context_proxy() as cursor:
            handler.execute(cursor)
            first_row = cursor.fetchone()
        if first_row is None:
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

    @overload
    async def execute_async(self, sql: str, params: Union["ParamType", "ListParamType"] = None) -> int: ...

    @overload
    async def execute_async(self, sql: str, *, param: Union["ParamType", "ListParamType"] = None) -> int: ...

    async def execute_async(self, sql, params=_PARAM_ALIAS_UNSET, *, param=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        if _is_empty_executemany_params(resolved_params):
            return 0

        handler = self.SqlParamHandler(sql, resolved_params)
        async with self.cursor() as cursor:
            return await handler.execute_async(cursor)

    async def _buffered_query(
        self, handler: BaseSqlParamHandler, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> List["_T"]:
        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            headers = get_col_names(cursor)
            try:
                validate_no_duplicate_columns(headers)
            except DuplicateColumnException:
                await self._on_duplicate_columns_async(cursor)
                raise
            data = await cursor.fetchall()
            return [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]

    async def _unbuffered_query(
        self, handler: BaseSqlParamHandler, model: Union[Type["_T"], Callable[..., "_T"]]
    ) -> AsyncGenerator["_T", None]:
        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            headers = get_col_names(cursor)
            try:
                validate_no_duplicate_columns(headers)
            except DuplicateColumnException:
                await self._on_duplicate_columns_async(cursor)
                raise

            row = await cursor.fetchone()
            if row is None:
                return

            yield serialize_dict_row(model, database_row_to_dict(headers, row))

            while True:
                row = await cursor.fetchone()
                if row is None:
                    break
                yield serialize_dict_row(model, database_row_to_dict(headers, row))

    async def _on_duplicate_columns_async(self, cursor: "AsyncCursorType") -> None:
        pass

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
        self,
        sql: str,
        model: Type[Dict] = dict,
        *,
        buffered: "Literal[True]" = True,
        params: Optional["ParamType"],
    ) -> List[Dict[str, Any]]: ...

    @overload
    async def query_async(
        self,
        sql: str,
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
        *,
        buffered: "Literal[False]",
    ) -> AsyncGenerator[Dict[str, Any], None]: ...

    @overload
    async def query_async(
        self,
        sql: str,
        model: Type[Dict] = dict,
        *,
        buffered: "Literal[False]",
        params: Optional["ParamType"],
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
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
        buffered: "Literal[True]" = True,
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

    @overload
    async def query_async(
        self,
        sql: str,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        buffered: "Literal[False]",
        params: Optional["ParamType"],
    ) -> AsyncGenerator["_T", None]: ...

    async def query_async(self, sql, model=dict, param=_PARAM_ALIAS_UNSET, buffered=True, *, params=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        handler = self.SqlParamHandler(sql, resolved_params)
        if buffered:
            records = await self._buffered_query(handler, model)
            return records
        return self._unbuffered_query(handler, model)

    @overload
    async def query_multiple_async(
        self, queries: Tuple[str, ...], models: Tuple[Any, ...] = None, param: Optional["ParamType"] = None
    ) -> Tuple[List[Any], ...]: ...

    @overload
    async def query_multiple_async(
        self, queries: Tuple[str, ...], models: Tuple[Any, ...] = None, *, params: Optional["ParamType"] = None
    ) -> Tuple[List[Any], ...]: ...

    async def query_multiple_async(
        self,
        queries: Tuple[str, ...],
        models: Tuple[Any, ...] = None,
        param=_PARAM_ALIAS_UNSET,
        *,
        params=_PARAM_ALIAS_UNSET,
    ) -> Tuple[List[Any], ...]:
        """
        :todo use TypeVarTuple for the variadic types of models once the mypy support is better such that type checkers
              and hinters will be able to infer which model type you're working with.  Leaving this as is for now...
        """
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)

        if models is None:
            models = cast(Tuple[dict], tuple(dict for _ in queries))

        if len(queries) != len(models):
            raise ValueError("Number of queries must equal number of models")

        results = list()
        async with self.cursor() as cursor:
            for query, model in zip(queries, models):
                handler = self.SqlParamHandler(query, resolved_params)
                await handler.execute_async(cursor)
                headers = get_col_names(cursor)
                data = await cursor.fetchall()

                if not data:
                    raise NoResultException(f"No results returned from query {query}")

                validate_no_duplicate_columns(headers)
                serialized_data = [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]
                results.append(serialized_data)

        return cast(Tuple[List[Any]], tuple(results))

    @overload
    async def query_first_async(
        self,
        sql: str,
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Dict[str, Any]: ...

    @overload
    async def query_first_async(
        self, sql: str, model: Type[Dict] = dict, *, params: Optional["ParamType"]
    ) -> Dict[str, Any]: ...

    @overload
    async def query_first_async(
        self,
        sql: str,
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> "_T": ...

    @overload
    async def query_first_async(
        self,
        sql: str,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
    ) -> "_T": ...

    async def query_first_async(self, sql, model=dict, param=_PARAM_ALIAS_UNSET, *, params=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        handler = self.SqlParamHandler(sql, resolved_params)

        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            headers = get_col_names(cursor)
            row = await cursor.fetchone()
            if row is None:
                raise NoResultException("Query returned no results")
            validate_no_duplicate_columns(headers)
            return serialize_dict_row(model, database_row_to_dict(headers, row))

    @overload
    async def query_first_or_default_async(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_first_or_default_async(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        model: Type[Dict] = dict,
        *,
        params: Optional["ParamType"],
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_first_or_default_async(
        self,
        sql: str,
        default: "_Default",
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_first_or_default_async(
        self,
        sql: str,
        default: "_Default",
        model: Type[Dict] = dict,
        *,
        params: Optional["ParamType"],
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
        default: Callable[[], "_Default"],
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
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

    @overload
    async def query_first_or_default_async(
        self,
        sql: str,
        default: "_Default",
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
    ) -> Union["_Default", "_T"]: ...

    async def query_first_or_default_async(
        self, sql, default, model=dict, param=_PARAM_ALIAS_UNSET, *, params=_PARAM_ALIAS_UNSET
    ):
        resolved_params = self._resolve_params(param, params)
        try:
            return await self.query_first_async(sql, model=model, param=resolved_params)
        except NoResultException:
            return _resolve_default_value(default)

    @overload
    async def query_single_async(
        self,
        sql: str,
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Dict[str, Any]: ...

    @overload
    async def query_single_async(
        self, sql: str, model: Type[Dict] = dict, *, params: Optional["ParamType"]
    ) -> Dict[str, Any]: ...

    @overload
    async def query_single_async(
        self,
        sql: str,
        param: Optional["ParamType"] = ...,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
    ) -> "_T": ...

    @overload
    async def query_single_async(
        self,
        sql: str,
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
    ) -> "_T": ...

    async def query_single_async(self, sql, model=dict, param=_PARAM_ALIAS_UNSET, *, params=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        handler = self.SqlParamHandler(sql, resolved_params)

        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            headers = get_col_names(cursor)
            data = await _fetch_at_most_two_rows_async(cursor)

        num_records = len(data)
        if num_records == 0:
            raise NoResultException("Expected exactly one record, got zero")
        elif num_records > 1:
            raise MoreThanOneResultException("Expected exactly one record, got at least two")

        validate_no_duplicate_columns(headers)
        return serialize_dict_row(model, database_row_to_dict(headers, data[0]))

    @overload
    async def query_single_or_default_async(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_single_or_default_async(
        self,
        sql: str,
        default: Callable[[], "_Default"],
        model: Type[Dict] = dict,
        *,
        params: Optional["ParamType"],
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_single_or_default_async(
        self,
        sql: str,
        default: "_Default",
        model: Type[Dict] = dict,
        param: Optional["ParamType"] = ...,
    ) -> Union["_Default", Dict[str, Any]]: ...

    @overload
    async def query_single_or_default_async(
        self,
        sql: str,
        default: "_Default",
        model: Type[Dict] = dict,
        *,
        params: Optional["ParamType"],
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
        default: Callable[[], "_Default"],
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
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

    @overload
    async def query_single_or_default_async(
        self,
        sql: str,
        default: "_Default",
        *,
        model: Union[Type["_T"], Callable[..., "_T"]],
        params: Optional["ParamType"],
    ) -> Union["_Default", "_T"]: ...

    async def query_single_or_default_async(
        self, sql, default, model=dict, param=_PARAM_ALIAS_UNSET, *, params=_PARAM_ALIAS_UNSET
    ):
        resolved_params = self._resolve_params(param, params)
        try:
            return await self.query_single_async(sql, model=model, param=resolved_params)
        except NoResultException:
            return _resolve_default_value(default)

    @overload
    async def execute_scalar_async(self, sql: str, params: Optional["ParamType"] = None) -> Any: ...

    @overload
    async def execute_scalar_async(self, sql: str, *, param: Optional["ParamType"] = None) -> Any: ...

    async def execute_scalar_async(self, sql, params=_PARAM_ALIAS_UNSET, *, param=_PARAM_ALIAS_UNSET):
        resolved_params = self._resolve_params(param, params)
        _raise_if_list_params_for_read(resolved_params)
        handler = self.SqlParamHandler(sql, resolved_params)
        async with self.cursor() as cursor:
            await handler.execute_async(cursor)
            first_row = await cursor.fetchone()
        if first_row is None:
            raise NoResultException("Query returned no results")
        return first_row[0]
