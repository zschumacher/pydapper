# pydapper
A pure python library inspired by the NuGet library [dapper](https://dapper-tutorial.net).

*pydapper* is built on top of the [dbapi 2.0 spec](https://www.python.org/dev/peps/pep-0249/)
to provide more convenient methods for working with databases in python.

## Help (TODO)
See the [documentation]() for more details.

## Installation
It is recommended to only install the database apis you need for your use case.  Example below is for psycopg2!
```bash
# pip 
pip install pydapper[psycopg2]
# poetry
poetry add pydapper -E psycopg2
```

## A Simple Example
```python
from dataclasses import dataclass
import datetime

from pydapper import connect


@dataclass
class Task:
    id: int
    description: str
    due_date: datetime.date

    
with connect("postgresql+psycopg2://pydapper:pydapper@locahost/pydapper") as conn:
    tasks = conn.query("select id, description, due_date from task;", model=Task)
    
print(tasks)
#> [Task(id=1, description='Add a README!', due_date=datetime.date(2022, 1, 16))]
```
(This script is complete, it should run "as is")
