[![test](https://github.com/zschumacher/pydapper/actions/workflows/test.yml/badge.svg)](https://github.com/zschumacher/pydapper/actions/workflows/test.yml)
[![PyPI version](https://badge.fury.io/py/pydapper.svg)](https://badge.fury.io/py/pydapper)
[![Documentation Status](https://readthedocs.org/projects/pydapper/badge/?version=latest)](https://pydapper.readthedocs.io/en/latest/?badge=latest)
[![codecov](https://codecov.io/gh/zschumacher/pydapper/branch/main/graph/badge.svg?token=3X1IR81HL2)](https://codecov.io/gh/zschumacher/pydapper)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pydapper)

# pydapper
A pure python library inspired by the NuGet library [dapper](https://dapper-tutorial.net).

*pydapper* is built on top of the [dbapi 2.0 spec](https://www.python.org/dev/peps/pep-0249/)
to provide more convenient methods for working with databases in python.

## Help
See the [documentation](https://pydapper.readthedocs.io/en/latest/) for more details.

## Installation
It is recommended to only install the database apis you need for your use case.  Example below is for psycopg2!
### pip
```console
pip install pydapper[psycopg2]
```

### poetry
```console
poetry add pydapper -E psycopg2
```

## Never write this again...
```python
from psycopg2 import connect

@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date

with connect("postgresql://pydapper:pydapper@localhost/pydapper") as conn:
    with conn.cursor() as cursor:
        cursor.execute("select id, description, due_date from task")
        headers = [i[0] for i in cursor.description]
        data = cursor.fetchall()

list_data = [Task(**dict(zip(headers, row))) for row in data]
```

## Instead, write...
```python
from dataclasses import dataclass
import datetime

import pydapper


@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date

    
with pydapper.connect("postgresql+psycopg2://pydapper:pydapper@locahost/pydapper") as commands:
    tasks = commands.query("select id, description, due_date from task;", model=Task)
```
(This script is complete, it should run "as is")
