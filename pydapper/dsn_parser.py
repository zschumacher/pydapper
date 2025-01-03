import dsnparse

class PydapperParseResult(dsnparse.ParseResult):
    # noinspection PyUnresolvedReferences
    def __init__(self, dsn: str, **defaults):
        super().__init__(dsn, **defaults)
        # make linters and editors happy
        self.dsn: str = self.dsn
        self.scheme: str = self.scheme
        self.path: str = self.path
        self.hostname: str = self.hostname
        self.username: str = self.username
        self.password: str = self.password
        self.query: Dict[str, str] = self.query  # dict of query string
        self.query_str: str = self.query_str  # raw query string
        self.port: str = self.port
        self.fragment: str = self.fragment

    def __repr__(self):
        result = [f"instance({self.__class__.__name__}):"]
        for k, v in vars(self).items():
            result.append(f"\t{k}: {v!r}")
        return "\n".join(result)

    def __eq__(self, other):
        return self.dsn == other.dsn

    @property
    def dbms(self) -> str:
        return self.schemes[0]

    @property
    def dbapi(self) -> str:
        dbapi = "_".join(self.schemes[1:])
        if not dbapi:
            raise ValueError(f"Could not derive dbapi from schemes {self.schemes}")
        return dbapi