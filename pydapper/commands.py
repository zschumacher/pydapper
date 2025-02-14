from .dbapi.pool import ConnectionPool
from .dbapi.cursor import CursorProxy
from .dbapi.connection import ConnectionProxy
from .parameters.enums import ParamStyle
from .dbapi.pool import acquire_and_release
import typing as t
from contextlib import contextmanager
from .parameters.format import FormatAdapter
from .parameters.named import NamedAdapter
from .parameters.pyformat import PyformatAdapter
from .parameters.qmark import QmarkAdapter
from .parameters.numeric import NumericAdapter
from .types import ParamType

@contextmanager
def execute(
    pool: ConnectionPool, cursor_proxy: t.Type[CursorProxy], sql: str, params: ParamType | None = None
) -> CursorProxy:
    passed_style = ParamStyle.detect(sql)
    if passed_style is None and params is not None:
        raise ValueError(f"Passed params but could not identify param style of query.  Must be one of {list(ParamStyle)}")

    if passed_style not in cursor_proxy.supported_param_styles:
        # grab first supported style as the target
        supported = cursor_proxy.supported_param_styles[0]

        if supported == ParamStyle.QMARK:
            adapter = QmarkAdapter(sql, params)
        elif supported == ParamStyle.NAMED:
            adapter = NamedAdapter(sql, params)
        elif supported == ParamStyle.FORMAT:
            adapter = FormatAdapter(sql, params)
        elif supported == ParamStyle.NUMERIC:
            adapter = NumericAdapter(sql, params)
        else:
            adapter = PyformatAdapter(sql, params)

        sql, params = adapter.normalize()

    with acquire_and_release(pool) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        yield cursor
        cursor.close()


class BaseCommands:
    ConnectionProxy: t.Type[ConnectionProxy] = ...
    CursorProxy: t.Type[CursorProxy] = ...
    ConnectionPool: t.Type[ConnectionPool] = ...
    SupportedParamStyles: list[ParamStyle] = ...

    def __init__(self, dsn: str, pool_size: int = 10, **connect_kwargs):
        self._pool = self.ConnectionPool(dsn, max_size=pool_size, **connect_kwargs)

    def __init_subclass__(cls, **kwargs):
        for attr in "ConnectionProxy", "CursorProxy", "ConnectionPool":
            assert hasattr(cls, attr), f"subclass must have class attribute {attr}"

    def execute(self, sql: str, params: ParamType | None = None) -> int:
        with execute(self._pool, sql, params) as cursor:
            return cursor.rowcount

    def query(self, sql: str, params: ParamType | None = None):
        with execute(self._pool, self.CursorProxy, sql, params) as cursor:
            results = cursor.fetchall()
            headers = [i[0] for i in cursor.description]
            return [
                dict(zip(headers, row)) for row in results
            ]
