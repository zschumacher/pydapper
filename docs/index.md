[![PyPI version](https://badge.fury.io/py/pydapper.svg)](https://badge.fury.io/py/pydapper)
[![Documentation Status](https://readthedocs.org/projects/pydapper/badge/?version=latest)](https://pydapper.readthedocs.io/en/latest/?badge=latest)
[![codecov](https://codecov.io/gh/zschumacher/pydapper/branch/main/graph/badge.svg?token=3X1IR81HL2)](https://codecov.io/gh/zschumacher/pydapper)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pydapper)


A pure python library inspired by the NuGet library [dapper](https://dapper-tutorial.net).

*pydapper* is built on top of the [database api (dbapi) 2.0 spec](https://www.python.org/dev/peps/pep-0249/)
to provide more convenient methods for working with databases in python.

## Example
```python
{!docs/../docs_src/methods/query/basic_query.py!}
```
(*This script is complete,  it should run "as is"*)

What's going on here?

* `connect` handles creating a connection and returning the pydapper entrypoint for the dsn you pass in
* the `query` method is executing the sql string and serializing each item in the result set to the model passed (`Task`)
* the context manager is a proxy to whatever the underlying dbapi for the specified DSN has implemented ([see database support docs](database_support/intro.md))


## Rationale
Why would I use *pydapper*?

**ORM queries are great...until they're not**
: Most ORMs in python (think SQLAlchemy, Django, Pony) provide an interface for mapping
  database results to python objects, but also implement their own api for interacting with the database.  When these
  queries become complex, they are often hard to read and debug.
  Why not use SQL instead?

**Safe from SQL injection**
: pydapper provides a consistent syntax for declaring query parameters and guarantees it is converted to the safest
  possible parameter substitution for the dbapi to deter SQL injection

**You want a framework that lets you BYOC (bring your own connection)**
: Sometimes ORM frameworks abstract *too* much from you.  *pydapper* allows you to use your own connection
  object and pass it into the `using` entrypoint.  This gives you complete control over connection management
  when you don't want *pydapper* to manage it for you.

**You use python dbapi interfaces often and are tired of writing this code**
```python
{!docs/../docs_src/anti_example.py!}
```

## Buy me a coffee
If you find this project useful, consider buying me a coffee!  

<a href="https://www.buymeacoffee.com/zachschumacher" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a>