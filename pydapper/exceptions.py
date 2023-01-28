class PyDapperException(Exception):
    pass


class NoResultException(PyDapperException):
    pass


class MoreThanOneResultException(PyDapperException):
    pass


class InvalidParamsException(PyDapperException):
    def __init__(self, *, query_params, param):
        msg = f"Parameters are invalid.  {query_params=!r} {param=!r}."
        super().__init__(msg)
