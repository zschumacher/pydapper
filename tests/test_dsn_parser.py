import pytest

from pydapper.dsn_parser import PydapperParseResult
from pydapper.dsn_parser import parse

SQLITE3_DSN = "sqlite+sqlite3://some.db"
PSYCOPG2_DSN = "postgresql+psycopg2://pydapper:password@localhost:5433/postgres"
PSYCOPG3_DSN = "postgresql+psycopg://pydapper:password@localhost:5433/postgres"
PYMSSQL_DSN = "mssql+pymssql://sa:pydapper!PYDAPPER@localhost:1433/master"
MYSQL_CONNECTOR_PYTHON_DSN = "mysql+mysql://pydapper:pydapper@localhost:3307/pydapper"
ORACLEDB_DSN = "oracle+oracledb://pydapper:pydapper@localhost:1522/pydapper"
AIOPG_DSN = "postgresql+aiopg://pydapper:pydapper@localhost:5433/postgres"
BIGQUERY_DSN = "bigquery+google:////"
SQLITE_DEFAULT_DSN = "sqlite://some.db"
POSTGRES_DEFAULT_DSN = "postgresql://pydapper:password@localhost:5433/postgres"
MSSQL_DEFAULT_DSN = "mssql://sa:pydapper!PYDAPPER@localhost:1433/master"
MYSQL_DEFAULT_DSN = "mysql://pydapper:pyapper@localhost:3307/pydapper"
ORACLE_DEFAULT_DSN = "oracle://pydapper:pydapper@localhost:1522/pydapper"
BIGQUERY_DEFAULT_DSN = "bigquery:////"


ALL_DSNS = [
    SQLITE3_DSN,
    PSYCOPG2_DSN,
    PSYCOPG3_DSN,
    PYMSSQL_DSN,
    MYSQL_CONNECTOR_PYTHON_DSN,
    ORACLEDB_DSN,
    AIOPG_DSN,
    BIGQUERY_DSN,
    SQLITE_DEFAULT_DSN,
    POSTGRES_DEFAULT_DSN,
    MSSQL_DEFAULT_DSN,
    MYSQL_DEFAULT_DSN,
    ORACLE_DEFAULT_DSN,
    BIGQUERY_DEFAULT_DSN,
]

pytestmark = pytest.mark.core


@pytest.mark.parametrize("dsn", ALL_DSNS)
def test_every_existing_and_documented_dsn_constructs(dsn):
    parsed = PydapperParseResult(dsn)

    assert parsed.dsn == dsn


@pytest.mark.parametrize("dsn", [None, 1, object()])
def test_non_string_dsn_is_rejected(dsn):
    with pytest.raises(TypeError):
        PydapperParseResult(dsn)


@pytest.mark.parametrize(
    ("dsn", "scheme", "schemes", "dbms", "dbapi"),
    [
        (SQLITE3_DSN, "sqlite+sqlite3", ["sqlite", "sqlite3"], "sqlite", "sqlite3"),
        (PSYCOPG2_DSN, "postgresql+psycopg2", ["postgresql", "psycopg2"], "postgresql", "psycopg2"),
        (PSYCOPG3_DSN, "postgresql+psycopg", ["postgresql", "psycopg"], "postgresql", "psycopg"),
        (AIOPG_DSN, "postgresql+aiopg", ["postgresql", "aiopg"], "postgresql", "aiopg"),
        (PYMSSQL_DSN, "mssql+pymssql", ["mssql", "pymssql"], "mssql", "pymssql"),
        (MYSQL_CONNECTOR_PYTHON_DSN, "mysql+mysql", ["mysql", "mysql"], "mysql", "mysql"),
        (ORACLEDB_DSN, "oracle+oracledb", ["oracle", "oracledb"], "oracle", "oracledb"),
        (BIGQUERY_DSN, "bigquery+google", ["bigquery", "google"], "bigquery", "google"),
        (SQLITE_DEFAULT_DSN, "sqlite", ["sqlite"], "sqlite", "sqlite3"),
        (POSTGRES_DEFAULT_DSN, "postgresql", ["postgresql"], "postgresql", "psycopg2"),
        (MSSQL_DEFAULT_DSN, "mssql", ["mssql"], "mssql", "pymssql"),
        (MYSQL_DEFAULT_DSN, "mysql", ["mysql"], "mysql", "mysql"),
        (ORACLE_DEFAULT_DSN, "oracle", ["oracle"], "oracle", "oracledb"),
        (BIGQUERY_DEFAULT_DSN, "bigquery", ["bigquery"], "bigquery", "google"),
    ],
)
def test_default_and_explicit_adapter_routing(dsn, scheme, schemes, dbms, dbapi):
    parsed = PydapperParseResult(dsn)

    assert parsed.scheme == scheme
    assert parsed.schemes == schemes
    assert parsed.dbms == dbms
    assert parsed.dbapi == dbapi


def test_explicit_third_party_adapter_preserves_exact_scheme_spelling():
    parsed = PydapperParseResult("Acme+AcmeDB://Host/Database")

    assert parsed.scheme == "Acme+AcmeDB"
    assert parsed.schemes == ["Acme", "AcmeDB"]
    assert parsed.dbms == "Acme"
    assert parsed.dbapi == "AcmeDB"


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "relative.db",
        "://host/database",
        "1postgresql://host/database",
        "some_db+tests://host/database",
        "postgresql+://host/database",
        "postgresql++psycopg://host/database",
        "postgresql+psycopg+extra://host/database",
        "postgresql:/database",
        "postgresql:database",
        "PostgreSQL://host/database",
        "dbname=postgres user=pydapper",
    ],
)
def test_missing_or_malformed_schemes_are_rejected_during_construction(dsn):
    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    assert "scheme" in str(exc_info.value).lower()


def test_unknown_one_component_scheme_is_rejected_during_construction():
    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult("unknown://host/database")

    assert "scheme" in str(exc_info.value).lower()
    assert "adapter" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    ("dsn", "expected_path", "expected_database"),
    [
        ("sqlite://relative.db", "", "relative.db"),
        ("sqlite+sqlite3://relative.db", "", "relative.db"),
        ("sqlite:///relative/path.db", "/relative/path.db", "relative/path.db"),
        ("sqlite:////absolute/path.db", "//absolute/path.db", "/absolute/path.db"),
        ("sqlite:///:memory:", "/:memory:", ":memory:"),
        ("sqlite://", "", ""),
        ("sqlite:///relative/my%20file%2Bname.db", "/relative/my file+name.db", "relative/my file+name.db"),
        ("sqlite://Relative%20File.db", "", "Relative File.db"),
        ("sqlite://directory/nested%20file.db", "/nested file.db", "directory/nested file.db"),
    ],
)
def test_sqlite_database_is_the_final_normalized_connection_target(dsn, expected_path, expected_database):
    parsed = PydapperParseResult(dsn)

    assert parsed.path == expected_path
    assert parsed.database == expected_database
    assert parsed.dbname == expected_database


@pytest.mark.parametrize(
    ("dsn", "expected_host", "expected_path", "expected_database"),
    [
        ("postgresql://host/database", "host", "/database", "database"),
        ("mysql://host/", "host", "/", ""),
        ("mssql://host", "host", "", ""),
        ("oracle://host/service%20name", "host", "/service name", "service name"),
        ("bigquery:////", None, "//", "//"),
        ("postgresql:///local%20database", None, "/local database", "/local database"),
        ("acme+driver://host/database%2Fname", "host", "/database/name", "database/name"),
    ],
)
def test_non_sqlite_database_normalization_preserves_host_distinctions(
    dsn, expected_host, expected_path, expected_database
):
    parsed = PydapperParseResult(dsn)

    assert parsed.host == expected_host
    assert parsed.path == expected_path
    assert parsed.database == expected_database
    assert parsed.dbname == expected_database


@pytest.mark.parametrize(
    ("dsn", "expected_path", "expected_database"),
    [
        ("postgresql://host/%2Fdatabase%2F", "//database/", "/database/"),
        ("sqlite:///%2Frelative%2F", "//relative/", "/relative/"),
        ("sqlite://directory/%2Ffile%2F", "//file/", "directory//file/"),
    ],
)
def test_database_normalization_removes_url_delimiters_before_percent_decoding(dsn, expected_path, expected_database):
    parsed = PydapperParseResult(dsn)

    assert parsed.path == expected_path
    assert parsed.database == expected_database


@pytest.mark.parametrize(
    ("authority", "expected_username", "expected_password"),
    [
        ("host", None, None),
        ("user@host", "user", None),
        ("user:@host", "user", ""),
        (":password@host", "", "password"),
        ("@host", "", None),
        ("user:part:secret@host", "user", "part:secret"),
        ("user:part%3Asecret@host", "user", "part:secret"),
        ("user%3Aname:password@host", "user:name", "password"),
        ("us%40er:p%40ss%3Aword%2Fend@host", "us@er", "p@ss:word/end"),
        ("user%2Fname:p%C3%A4ssword@host", "user/name", "pässword"),
    ],
)
def test_user_information_is_delimited_before_percent_decoding(authority, expected_username, expected_password):
    parsed = PydapperParseResult(f"postgresql://{authority}/database")

    assert parsed.username == expected_username
    assert parsed.user == expected_username
    assert parsed.password == expected_password


@pytest.mark.parametrize(
    ("dsn", "expected_hostname", "expected_port", "expected_hostloc"),
    [
        ("postgresql://Example.COM/database", "example.com", None, "example.com"),
        ("postgresql://127.0.0.1:5432/database", "127.0.0.1", 5432, "127.0.0.1:5432"),
        ("postgresql://db%2Dhost:0/database", "db-host", 0, "db-host:0"),
        ("postgresql://host:65535/database", "host", 65535, "host:65535"),
        ("oracle://[2001:db8::1]:1521/service", "2001:db8::1", 1521, "[2001:db8::1]:1521"),
        ("oracle://[2001:db8::1]/service", "2001:db8::1", None, "[2001:db8::1]"),
        ("bigquery:////", None, None, ""),
    ],
)
def test_host_port_and_hostloc(dsn, expected_hostname, expected_port, expected_hostloc):
    parsed = PydapperParseResult(dsn)

    assert parsed.hostname == expected_hostname
    assert parsed.host == expected_hostname
    assert parsed.port == expected_port
    assert parsed.hostloc == expected_hostloc


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://host:not-a-number/database",
        "postgresql://host:-1/database",
        "postgresql://host:65536/database",
        "postgresql://host:12:34/database",
        "postgresql://host:/database",
        "postgresql://:5432/database",
    ],
)
def test_invalid_ports_are_rejected_during_construction(dsn):
    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    message = str(exc_info.value).lower()
    assert "port" in message or "authority" in message


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://host:\n5432/database",
        "postgresql://host:54\t32/database",
        "postgresql://host:\r5432/database",
        "postgresql://user:control\x00secret@host/database",
    ],
)
def test_raw_control_characters_are_rejected_before_url_parsing(dsn):
    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    error_text = repr(exc_info.value)
    assert "control" in error_text.lower() or "syntax" in error_text.lower()
    assert "control\x00secret" not in error_text
    assert exc_info.value.__context__ is None


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://host name/database",
        "postgresql://host%20name/database",
        "postgresql://[v1.future]:5432/database",
        "postgresql://[v1.foo:bar]/database",
        "postgresql://host%3A5432/database",
        "postgresql://2001%3Adb8%3A%3A1/database",
        "postgresql://%5Bnot-ip%5D/database",
        "postgresql://host%2Fname/database",
        "postgresql://host%40name/database",
    ],
)
def test_unsupported_or_malformed_host_syntax_is_rejected(dsn):
    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    assert "host" in str(exc_info.value).lower() or "authority" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    "encoded_host",
    [
        "host%EF%BC%9A5432",
        "host%EF%BC%8Fname",
        "host%EF%BC%9Fquery",
        "host%EF%BC%83fragment",
        "host%EF%BC%A0name",
        "host%EF%BC%8Cother",
        "%EF%BC%BBnot-ip%EF%BC%BD",
        "host%EF%BC%BCname",
        "host%E2%84%80name",
        "host%5Bname",
        "host%5Dname",
        "host%5Cname",
        "host%3Fname",
        "host%23name",
        "host%00name",
        "host%1Fname",
        "host%7Fname",
        "host%C2%85name",
        "host%ED%A0%80name",
        "host%FFname",
        "host%ZZname",
        "%F0%9F%98%80.example",
        "a%E2%81%84b.example",
        "a%E2%88%95b.example",
    ],
)
def test_encoded_unicode_delimiters_and_controls_are_rejected_safely(encoded_host):
    encoded_secret = "unicode%3Asecret%2Fsentinel"
    decoded_secret = "unicode:secret/sentinel"
    dsn = f"postgresql://user:{encoded_secret}@{encoded_host}/database"

    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    error_text = repr(exc_info.value)
    assert "host" in error_text.lower() or "authority" in error_text.lower()
    assert dsn not in error_text
    assert encoded_secret not in error_text
    assert decoded_secret not in error_text
    assert exc_info.value.__context__ is None


def test_literal_surrogate_in_host_is_rejected_safely():
    dsn = "postgresql://user:surrogate-secret@host\ud800/database"

    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    assert "host" in str(exc_info.value).lower() or "authority" in str(exc_info.value).lower()
    assert "surrogate-secret" not in repr(exc_info.value)
    assert exc_info.value.__context__ is None


def test_encoded_unicode_hostname_remains_decoded():
    parsed = PydapperParseResult("postgresql://m%C3%BCnich.example/database")

    assert parsed.hostname == "münich.example"
    assert parsed.hostloc == "münich.example"


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://例え。テスト/database",
        "postgresql://%E4%BE%8B%E3%81%88%EF%BD%A1%E3%83%86%E3%82%B9%E3%83%88/database",
    ],
)
def test_standard_idna_dot_equivalents_remain_valid(dsn):
    parsed = PydapperParseResult(dsn)

    assert parsed.hostname in {"例え。テスト", "例え｡テスト"}


def test_idna_encoding_error_is_credential_safe():
    encoded_secret = "idna%3Asecret%2Fsentinel"
    decoded_secret = "idna:secret/sentinel"
    overlong_unicode_label = "é" * 64
    dsn = f"postgresql://user:{encoded_secret}@{overlong_unicode_label}/database"

    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    error_text = repr(exc_info.value)
    assert "host" in error_text.lower() or "authority" in error_text.lower()
    assert dsn not in error_text
    assert encoded_secret not in error_text
    assert decoded_secret not in error_text
    assert exc_info.value.__context__ is None


@pytest.mark.parametrize("hostname", ["a" * 64, "a..b", "foo_bar"])
def test_valid_ascii_reg_names_are_not_restricted_by_dns_rules(hostname):
    parsed = PydapperParseResult(f"postgresql://{hostname}/database")

    assert parsed.hostname == hostname


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://host-one,host-two/database",
        "postgresql://host-one%2Chost-two/database",
    ],
)
def test_multiple_hosts_are_not_supported(dsn):
    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    assert "host" in str(exc_info.value).lower() or "authority" in str(exc_info.value).lower()


def test_path_uses_url_decoding_without_treating_plus_as_space():
    parsed = PydapperParseResult("postgresql://host/my+database%20name")

    assert parsed.path == "/my+database name"
    assert parsed.database == "my+database name"


def test_query_text_and_decoded_parameters_preserve_strings_repeats_and_blanks():
    query = (
        "single=value&repeat=first&repeat=second&repeat=third&blank=&bare&unicode=caf%C3%A9&space=a+b"
        "&literal_plus=a%2Bb"
        "&integer=001&decimal=1.5&true=true&false=false"
    )
    parsed = PydapperParseResult(f"postgresql://host/database?{query}")

    assert parsed.query == query
    assert parsed.query_str == query
    assert parsed.query_params == {
        "single": "value",
        "repeat": ["first", "second", "third"],
        "blank": "",
        "bare": "",
        "unicode": "café",
        "space": "a b",
        "literal_plus": "a+b",
        "integer": "001",
        "decimal": "1.5",
        "true": "true",
        "false": "false",
    }
    assert all(
        isinstance(value, (str, list)) and (not isinstance(value, list) or all(isinstance(item, str) for item in value))
        for value in parsed.query_params.values()
    )


def test_query_keys_are_decoded_and_repeated_in_encounter_order():
    parsed = PydapperParseResult("postgresql://host/database?na%6De=one&name=two&%E2%9C%93=yes")

    assert parsed.query_params == {"name": ["one", "two"], "✓": "yes"}


def test_fragment_is_preserved_as_encoded_text():
    parsed = PydapperParseResult("postgresql://host/database#fragment%20value")

    assert parsed.fragment == "fragment%20value"


def test_equality_uses_the_raw_dsn_and_handles_unrelated_objects():
    dsn = "postgresql://host/database"

    assert PydapperParseResult(dsn) == PydapperParseResult(dsn)
    assert PydapperParseResult(dsn) != PydapperParseResult(f"{dsn}?option=value")
    assert PydapperParseResult(dsn) != object()


def test_repr_redacts_raw_encoded_and_decoded_credentials():
    encoded_secret = "repr%3Asecret%2Fsentinel"
    decoded_secret = "repr:secret/sentinel"
    dsn = f"postgresql://user:{encoded_secret}@database.example/app"

    representation = repr(PydapperParseResult(dsn))

    assert "PydapperParseResult" in representation
    assert "<redacted>" in representation
    assert dsn not in representation
    assert encoded_secret not in representation
    assert decoded_secret not in representation


@pytest.mark.parametrize(
    ("dsn", "component"),
    [
        ("some_bad://user:error%3Asecret%2Fsentinel@host/database", "scheme"),
        ("postgresql://user:error%3Asecret%2Fsentinel@host:bad/database", "port"),
        ("postgresql://user:error%3Asecret%2Fsentinel@[2001:db8::1/database", "authority"),
        ("postgresql://user:error%3Asecret%2Fsentinel@host／unsafe/database", "authority"),
    ],
)
def test_parser_errors_identify_the_component_without_retaining_credentials(dsn, component):
    encoded_secret = "error%3Asecret%2Fsentinel"
    decoded_secret = "error:secret/sentinel"

    with pytest.raises(ValueError) as exc_info:
        PydapperParseResult(dsn)

    error_text = repr(exc_info.value)
    assert component in error_text.lower()
    assert dsn not in error_text
    assert encoded_secret not in error_text
    assert decoded_secret not in error_text
    assert exc_info.value.__context__ is None


def test_parse_is_the_public_class_alias():
    dsn = "postgresql://host/database"

    assert parse is PydapperParseResult
    assert isinstance(parse(dsn), PydapperParseResult)
    assert parse(dsn) == PydapperParseResult(dsn)


def test_unconsumed_dsnparse_conveniences_are_not_part_of_the_result():
    parsed = PydapperParseResult("postgresql://host/database")

    for name in ("fields", "geturl", "parser", "paths", "setdefault"):
        assert not hasattr(parsed, name)
    with pytest.raises(TypeError):
        iter(parsed)
    with pytest.raises(TypeError):
        parsed[0]  # type: ignore[index]


def test_constructor_default_injection_is_not_supported():
    with pytest.raises(TypeError):
        PydapperParseResult("postgresql://host/database", port=5432)  # type: ignore[call-arg]
