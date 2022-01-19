
`query_multiple` can execute multiple queries with the same cursor and serialize the results. This method
will throw a `ValueError` if you don't supply the same numbe of queries and models.

## Parameters
| name  | type        | description                                                                                   | optional     | default |
|-------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql   | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
| param | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |

# Example
Query two tables and return the serialized results.
```python
{!docs/../docs_src/methods/query_multiple/example.py!}
```
(This script is complete, it should run "as is")