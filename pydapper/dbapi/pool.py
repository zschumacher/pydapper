import functools
import threading
from queue import Queue
from .connection import ConnectionProxy
import queue
import logging
from typing import Type
from contextlib import contextmanager
from ..dsn_parser import PydapperParseResult

logger = logging.getLogger(__name__)


@contextmanager
def acquire_and_release(pool: "ConnectionPool"):
    conn = pool.acquire()
    yield conn
    pool.release(conn)


class ConnectionPool:
    ConnectionProxy: Type[ConnectionProxy]

    def __init__(self, dsn: str, max_size=10, **connect_kwargs):
        self._dsn = dsn
        self._max_size = max_size
        self._pool = queue.Queue(maxsize=max_size)
        self._connect_kwargs = connect_kwargs
        self._lock = threading.Lock()
        self._pool_name = self.__class__.__name__

    def __init_subclass__(cls, **kwargs):
        assert hasattr(
            cls, "ConnectionProxy"
        ), "subclasses of ConnectionPool must define a class level ConnectionProxy"

    @functools.cached_property
    def dsn(self) -> PydapperParseResult:
        return PydapperParseResult(self._dsn)

    def acquire(self):
        with self._lock:
            try:
                conn = self._pool.get_nowait()
                logger.debug(f"Acquired connection from pool {self._pool_name}")
                return conn
            except queue.Empty:
                if self._pool.qsize() < self._max_size:
                    logger.debug(f"Creating new connection in pool {self._pool_name}")
                    return self.ConnectionProxy.connect(
                        self.dsn, **self._connect_kwargs
                    )
                logger.debug(f"Waiting for new connection")
                return self._pool.get()

    def release(self, connection):
        with self._lock:
            try:
                self._pool.put_nowait(connection)
                logger.debug(f"Release connection back to pool {self._pool_name}")
            except queue.Full:
                logger.debug(
                    f"Pool {self._pool_name} is full, closing unneeded connection"
                )
                connection.close()

    def close_all(self):
        logger.debug(f"Closing all connections in pool {self._pool_name}")
        with self._lock:
            while not self._pool.empty():
                connection = self._pool.get_nowait()
                try:
                    connection.close()
                except Exception as e:
                    logger.exception(e)

    def reset(self):
        self.close_all()
        self._pool = Queue(maxsize=self._max_size)
        logger.info(f"Reset pool {self._pool_name}")
