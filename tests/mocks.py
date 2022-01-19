from faker import Faker

from pydapper.commands import BaseSqlParamHandler
from pydapper.commands import Commands


class MockCursor:
    def __init__(self):
        self.faker = Faker()
        self.rowcount = 0

    @property
    def description(self):
        return ("id", "int"), ("name", "text")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def execute(self, sql, parameters):
        if "insert" in sql or "update" in sql:
            self.rowcount = 1

    def fetchone(self):
        return 1, self.faker.name()

    def fetchall(self):
        return (1, self.faker.name()), (2, self.faker.name())

    def executemany(self, sql, params):
        self.rowcount = len(params)

    def close(self):
        self.rowcount = 0


class MockConnection:
    def __init__(self):
        self.closed = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def cursor(self, *args, **kwargs):
        return MockCursor()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = 1


class MockParamHandler(BaseSqlParamHandler):
    def get_param_placeholder(self, param_name) -> str:
        return "%s"


class MockCommands(Commands):
    SqlParamHandler = MockParamHandler

    @classmethod
    def connect(cls, parsed_dsn, **connect_kwargs):
        return cls(MockConnection())
