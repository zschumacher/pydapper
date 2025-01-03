from .dbapi.pool import ConnectionPool
from .dbapi.cursor import CursorProxy
from .dbapi.connection import ConnectionProxy
from .dbapi.pool import acquire_and_release

class BaseCommands:

    ConnectionProxy: t.Type[ConnectionProxy] = ...
    CursorProxy: t.Type[CursorProxy] = ...
    ConnectionPool: t.Type[ConnectionPool] = ...

    def __init__(self, connect_timeout: int = None, pool_size: int = 10, **connect_kwargs):
        self._connect_timeout = connect_timeout
        self._pool_size = pool_size
        self._connect_kwargs = connect_kwargs
        self._pool = ConnectionPool(connect_timeout=connect_timeout, pool_size=pool_size, **self._connect_kwargs)

    def __init_subclass__(cls, **kwargs):
        for attr in "ConnectionProxy", "CursorProxy", "ConnectionPool":
            assert hasattr(cls, attr), f"subclass must have class attribute {attr}"

    def execute(self, sql: str):
        with acquire_and_release(self._pool, self._connect_timeout) as conn:
            cursor = self.CursorProxy(conn.cursor())