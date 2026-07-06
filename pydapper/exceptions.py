class PyDapperException(Exception):
    pass


class NoResultException(PyDapperException):
    pass


class MoreThanOneResultException(PyDapperException):
    pass


class MissingParameterException(PyDapperException):
    pass


class UnsupportedFeatureError(PyDapperException):
    pass


class RowMappingException(PyDapperException):
    pass
