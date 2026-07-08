
`query_multiple` can execute multiple queries with the same cursor and serialize the results. This method
will throw a `ValueError` if you don't supply the same number of queries and models.

## Parameters
| name  | type        | description                                                                                   | optional     | default |
|-------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql   | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
| params | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |

`param=` remains accepted as a 1.x compatibility alias for `params=`. Pass only one of the two names.

{!docs/.parameter_shapes_read.md!}

{!docs/.row_mapping.md!}

## Example
Query two tables and return the serialized results.
```python
{!docs/../docs_src/methods/query_multiple/example.py!}
```
(This script is complete, it should run "as is")
