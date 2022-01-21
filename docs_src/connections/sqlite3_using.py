import pydapper
from collections import deque
import sqlite3


class SimplePool:
    """ sqlite3 does not provide a pool interface, this is a simple example that should never be used in production """

    def __init__(self, database: str):
        self._database = database
        self._connections = deque()

    def getconn(self):
        if len(self._connections) == 0:
            return sqlite3.connect(self._database)
        return self._connections.pop()

    def putconn(self, conn):
        self._connections.append(conn)

    def __del__(self):
        for conn in self._connections:
            conn.close()


my_pool = SimplePool("pydapper.db")

commands = pydapper.using(my_pool.getconn())
print(type(commands))
# <class 'pydapper.sqlite.sqlite3.Sqlite3Commands'>

print(type(commands.connection))
# <class 'sqlite3.Connection'>

my_pool.putconn(commands.connection)
