class PyDapperException(Exception):
    pass


class NoResultException(PyDapperException):
    pass


class MoreThanOneResultException(PyDapperException):
    pass
