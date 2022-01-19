import re
from abc import ABC
from abc import abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING
from typing import Any
from typing import Type
from typing import Union
from typing import cast

from .exceptions import MoreThanOneResultException
from .exceptions import NoResultException
from .utils import database_row_to_dict
from .utils import get_col_names
from .utils import safe_getattr
from .utils import serialize_dict_row

if TYPE_CHECKING:
    from .dsn_parser import PydapperParseResult
    from .types import ConnectionType
    from .types import CursorType
    from .types import ListParamType
    from .types import ParamType


class BaseSqlParamHandler(ABC):
    _PARAM_REGEX = "\\?(.*?)\\?"

    def __init__(self, sql: str, param: Union["ParamType", "ListParamType"] = None):
        self._sql = sql
        self._param = param
        if isinstance(self._param, list):
            all_params_are_same_type = all(
                isinstance(param, param_type := type(self._param[0])) for param in self._param[1:]
            )
            if not all_params_are_same_type:
                raise ValueError(f"All objects in params must be of type {param_type!r}")

    @abstractmethod
    def get_param_placeholder(self, param_name: str) -> str:
        ...

    @cached_property
    def ordered_param_names(self) -> tuple[str, ...]:
        matches = re.findall(BaseSqlParamHandler._PARAM_REGEX, self._sql)
        matches = cast(list[str], matches)
        return tuple(matches)

    @cached_property
    def ordered_param_values(self) -> Union[tuple[Any, ...], list[tuple[Any, ...]]]:
        if isinstance(self._param, list):
            return [tuple(safe_getattr(p, name) for name in self.ordered_param_names) for p in self._param]

        return tuple(safe_getattr(self._param, name) for name in self.ordered_param_names)

    @cached_property
    def prepared_sql(self):
        pattern = re.compile("|".join(re.escape(f"?{name}?") for name in self.ordered_param_names))
        return pattern.sub(self.get_param_placeholder, self._sql)  # type: ignore

    def execute(self, cursor: "CursorType") -> int:
        if self._param:
            sql = self.prepared_sql
            param_values = self.ordered_param_values
        else:
            sql = self._sql
            param_values = tuple()

        if isinstance(self.ordered_param_values, list):
            cursor.executemany(sql, param_values)
        else:
            cursor.execute(sql, param_values)

        return cursor.rowcount


class DefaultSqlParamHandler(BaseSqlParamHandler):
    def get_param_placeholder(self, param_name: str) -> str:
        return "%s"


class Commands(ABC):
    SqlParamHandler: Type[BaseSqlParamHandler] = DefaultSqlParamHandler

    def __init__(self, connection: "ConnectionType"):
        self.connection = connection

    def __enter__(self) -> "Commands":
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self.connection.__exit__(exc_type, exc_val, exc_tb)

    @classmethod
    @abstractmethod
    def connect(cls, parsed_dsn: "PydapperParseResult", **connect_kwargs) -> "Commands":
        ...

    def cursor(self, *args, **kwargs) -> "CursorType":
        return self.connection.cursor(*args, **kwargs)

    def execute(self, sql: str, param: Union["ParamType", "ListParamType"] = None) -> int:
        handler = self.SqlParamHandler(sql, param)
        with self.cursor() as cursor:
            rowcount = handler.execute(cursor)
        return rowcount

    def query(self, sql: str, model: Any = dict, param: "ParamType" = None) -> list[Any]:
        handler = self.SqlParamHandler(sql, param)
        with self.cursor() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            data = cursor.fetchall()
        return [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]

    def query_multiple(
        self, queries: tuple[str], models: tuple[Any] = None, param: "ParamType" = None
    ) -> tuple[list[Any], ...]:
        if models is None:
            models = cast(tuple[dict], tuple(dict for _ in queries))

        if len(queries) != len(models):
            raise ValueError("Number of queries must equal number of models")

        results = list()
        with self.cursor() as cursor:
            for query, model in zip(queries, models):
                handler = self.SqlParamHandler(query, param)
                handler.execute(cursor)
                headers = get_col_names(cursor)
                data = cursor.fetchall()

                if not data:
                    raise NoResultException(f"No results returned from query {query}")

                serialized_data = [serialize_dict_row(model, database_row_to_dict(headers, row)) for row in data]
                results.append(serialized_data)

        return cast(tuple[list[Any]], tuple(results))

    def query_first(
        self,
        sql: str,
        model: Any = dict,
        param: "ParamType" = None,
    ) -> Any:
        handler = self.SqlParamHandler(sql, param)

        with self.cursor() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            row = cursor.fetchone()
            if not row:
                raise NoResultException("Query returned no results")
        return serialize_dict_row(model, database_row_to_dict(headers, row))

    def query_first_or_default(self, sql: str, default: Any, model: Any = dict, param: Any = None) -> Any:
        try:
            return self.query_first(sql, model=model, param=param)
        except NoResultException:
            return default() if callable(default) else default

    def query_single(
        self,
        sql: str,
        model: Any = dict,
        param: "ParamType" = None,
    ) -> Any:
        handler = self.SqlParamHandler(sql, param)

        with self.cursor() as cursor:
            handler.execute(cursor)
            headers = get_col_names(cursor)
            data = cursor.fetchall()

        if (num_records := len(data)) == 0:
            raise NoResultException("Expected exactly one record, got zero")
        elif num_records > 1:
            raise MoreThanOneResultException(f"Expected exactly one record, got {num_records}")

        return serialize_dict_row(model, database_row_to_dict(headers, data[0]))

    def query_single_or_default(self, sql: str, default: Any, model: Any = dict, param: Any = None) -> Any:
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
        with self.cursor() as cursor:
            handler.execute(cursor)
            first_row = cursor.fetchone()
        if not first_row:
            raise NoResultException("Query returned no results")
        return first_row[0]
