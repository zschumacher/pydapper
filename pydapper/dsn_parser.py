import re
import unicodedata
from ipaddress import IPv6Address
from urllib.parse import SplitResult as _SplitResult
from urllib.parse import parse_qsl
from urllib.parse import unquote
from urllib.parse import urlsplit

_DEFAULT_DB_API = {
    "postgresql": "psycopg2",
    "sqlite": "sqlite3",
    "mssql": "pymssql",
    "mysql": "mysql",
    "oracle": "oracledb",
    "bigquery": "google",
}

_RAW_SCHEME = re.compile(r"^([^:/?#]+):")
_VALID_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_REG_NAME_ASCII_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+;=")
_UNSAFE_HOST_CHARACTERS = frozenset("/?:#@[],\\")
_IDNA_DOT_EQUIVALENTS = str.maketrans({"\u3002": ".", "\uff61": "."})


def _split_url(dsn: str) -> _SplitResult:
    invalid_authority = False
    try:
        result = urlsplit(dsn)
    except (UnicodeError, ValueError):
        invalid_authority = True

    if invalid_authority:
        # urllib errors can include the complete netloc, including credentials.
        # Raise outside the except block so the unsafe error is not retained as
        # exception context.
        raise ValueError("Invalid DSN authority")

    return result


def _parse_port(result: _SplitResult) -> int | None:
    invalid_port = False
    try:
        port = result.port
    except ValueError:
        invalid_port = True

    # urlsplit accepts a trailing colon as an absent port. In a pydapper DSN it
    # is a supplied but structurally invalid port component.
    if result.netloc.endswith(":"):
        invalid_port = True

    if invalid_port:
        raise ValueError("Invalid DSN port")

    return port


def _parse_query_params(query: str) -> dict[str, str | list[str]]:
    params: dict[str, str | list[str]] = {}
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key not in params:
            params[key] = value
        else:
            existing = params[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                params[key] = [existing, value]
    return params


def _validate_hostname(hostname: str, encoded_hostname: str, netloc: str) -> None:
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in hostname):
        raise ValueError("Invalid DSN authority; controls are not allowed in a host")
    if any(character.isspace() for character in hostname):
        raise ValueError("Invalid DSN authority; whitespace is not allowed in a host")

    # urllib applies this safety check to the original authority, but encoded
    # Unicode characters are still encoded at that point. Apply it again after
    # decoding so NFKC-equivalent delimiters cannot bypass authority parsing.
    normalized_without_colons = unicodedata.normalize("NFKC", hostname.replace(":", ""))
    if any(character in _UNSAFE_HOST_CHARACTERS for character in normalized_without_colons):
        raise ValueError("Invalid DSN authority; invalid delimiter in host")

    if ":" in hostname or "[" in netloc or "]" in netloc:
        invalid_ipv6 = False
        try:
            IPv6Address(hostname)
        except ValueError:
            invalid_ipv6 = True
        # A colon introduced only by percent-decoding was data in an
        # unbracketed reg-name, not valid IPv6 authority syntax.
        if invalid_ipv6 or ":" not in encoded_hostname:
            raise ValueError("Invalid DSN authority; IPv6 hosts must be bracketed literals")
        return

    normalized_hostname = unicodedata.normalize("NFKC", hostname).translate(_IDNA_DOT_EQUIVALENTS)
    if any(character.isascii() and character not in _REG_NAME_ASCII_CHARACTERS for character in normalized_hostname):
        raise ValueError("Invalid DSN authority; invalid character in host")

    if not normalized_hostname.isascii():
        if any(
            not character.isascii() and unicodedata.category(character)[0] not in {"L", "M", "N"}
            for character in normalized_hostname
        ):
            raise ValueError("Invalid DSN authority; invalid Unicode host")

        invalid_idna = False
        idna_hostname = ""
        try:
            idna_hostname = normalized_hostname.encode("idna").decode("ascii")
        except UnicodeError:
            invalid_idna = True
        if invalid_idna or any(character not in _REG_NAME_ASCII_CHARACTERS for character in idna_hostname):
            # Raise outside the except block so the rejected hostname is not
            # kept in exception context.
            raise ValueError("Invalid DSN authority; invalid Unicode host")


class PydapperParseResult:
    """The parsed, typed subset of URL-style DSNs supported by pydapper."""

    __slots__ = (
        "_database",
        "_dbapi",
        "_dbms",
        "dsn",
        "fragment",
        "hostname",
        "password",
        "path",
        "port",
        "query",
        "query_params",
        "scheme",
        "schemes",
        "username",
    )

    dsn: str
    scheme: str
    schemes: list[str]
    username: str | None
    password: str | None
    hostname: str | None
    port: int | None
    path: str
    query: str
    query_params: dict[str, str | list[str]]
    fragment: str
    _dbms: str
    _dbapi: str
    _database: str

    def __init__(self, dsn: str):
        if not isinstance(dsn, str):
            raise TypeError("dsn must be a string")
        if any(ord(character) < 32 or ord(character) == 127 for character in dsn):
            raise ValueError("Invalid DSN syntax; raw control characters are not allowed")

        scheme_match = _RAW_SCHEME.match(dsn)
        if scheme_match is None:
            raise ValueError("Invalid or missing DSN scheme")

        scheme = scheme_match.group(1)
        if _VALID_SCHEME.fullmatch(scheme) is None:
            raise ValueError("Invalid DSN scheme")
        if not dsn[scheme_match.end() :].startswith("//"):
            raise ValueError("Invalid DSN scheme delimiter")

        schemes = scheme.split("+")
        if len(schemes) > 2 or any(not component for component in schemes):
            raise ValueError("Invalid DSN scheme components; expected database[+adapter]")

        dbms = schemes[0]
        if len(schemes) == 2:
            dbapi = schemes[1]
        else:
            dbapi = _DEFAULT_DB_API.get(dbms, "")
            if not dbapi:
                raise ValueError("Unknown DSN database scheme; no default adapter is available")

        result = _split_url(dsn)
        hostname = result.hostname
        port = _parse_port(result)
        if port is not None and hostname is None:
            raise ValueError("Invalid DSN authority; a port requires a host")
        decoded_hostname = unquote(hostname) if hostname is not None else None
        sqlite_scheme = dbms.lower() == "sqlite"
        if not sqlite_scheme and decoded_hostname is not None:
            assert hostname is not None
            if "," in decoded_hostname:
                raise ValueError("Invalid DSN authority; multiple hosts are not supported")
            _validate_hostname(decoded_hostname, hostname, result.netloc)

        self.dsn = dsn
        self.scheme = scheme
        self.schemes = schemes
        self._dbms = dbms
        self._dbapi = dbapi
        self.username = unquote(result.username) if result.username is not None else None
        self.password = unquote(result.password) if result.password is not None else None
        self.hostname = decoded_hostname
        self.port = port
        self.path = unquote(result.path)
        self.query = result.query
        self.query_params = _parse_query_params(result.query)
        self.fragment = result.fragment
        sqlite_authority = None
        if (
            sqlite_scheme
            and result.netloc
            and result.username is None
            and result.password is None
            and self.port is None
            and ":" not in result.netloc
        ):
            # A SQLite authority is also the first filesystem path component.
            # urlsplit correctly parses it as a host, but its hostname property
            # is lowercased. Use the already parsed authority when it contains
            # only that host so case-sensitive filenames retain their spelling.
            sqlite_authority = unquote(result.netloc)
        self._database = self._normalize_database(result.path, sqlite_authority)

    def _normalize_database(self, encoded_path: str, sqlite_authority: str | None) -> str:
        if self.dbms.lower() != "sqlite":
            if self.hostname is None:
                return self.path
            return unquote(encoded_path.strip("/"))

        if self.hostname is None:
            # With an empty authority, the first slash belongs to URL syntax.
            # Each additional slash is part of the SQLite filesystem target.
            normalized_path = encoded_path[1:] if encoded_path.startswith("/") else encoded_path
            return unquote(normalized_path)

        authority = sqlite_authority if sqlite_authority is not None else self.hostname
        assert authority is not None
        path = unquote(encoded_path.strip("/"))
        if not path:
            return authority
        return f"{authority}/{path}"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(dsn='<redacted>', scheme={self.scheme!r}, "
            f"dbms={self.dbms!r}, dbapi={self.dbapi!r}, hostname={self.hostname!r}, port={self.port!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PydapperParseResult):
            return NotImplemented
        return self.dsn == other.dsn

    @property
    def dbms(self) -> str:
        return self._dbms

    @property
    def dbapi(self) -> str:
        return self._dbapi

    @property
    def user(self) -> str | None:
        return self.username

    @property
    def host(self) -> str | None:
        return self.hostname

    @property
    def hostloc(self) -> str:
        if self.hostname is None:
            return ""
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        if self.port is not None:
            return f"{host}:{self.port}"
        return host

    @property
    def database(self) -> str:
        return self._database

    @property
    def dbname(self) -> str:
        return self.database

    @property
    def query_str(self) -> str:
        return self.query


parse = PydapperParseResult
