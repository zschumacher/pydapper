SQLITE3_DSN = "sqlite+sqlite3://some.db"
PSYCOPG2_DSN = "postgresql+psycopg2://pydapper:password@localhost:5433/postgres"
PYMSSQL_DSN = "mssql+pymssql://sa:pydapper!PYDAPPER@localhost:1433/master"
SQLITE_DEFAULT_DSN = "sqlite://some.db"
POSTGRES_DEFAULT_DSN = "postgresql://pydapper:password@localhost:5433/postgres"
MSSQL_DEFAULT_DSN = "mssql://sa:pydapper!PYDAPPER@localhost:1433/master"

MOCK_DSN = "some_db+tests://localhost"

ALL_DSNS = [SQLITE3_DSN, PSYCOPG2_DSN, PYMSSQL_DSN, SQLITE_DEFAULT_DSN, POSTGRES_DEFAULT_DSN, MSSQL_DEFAULT_DSN]
