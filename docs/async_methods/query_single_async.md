 
`query_single_async` can execute a query and serialize the first result.  It throws an exception if there is not exactly one 
record in the result set.

## Parameters
| name  | type        | description                                                                                   | optional     | default |
|-------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql   | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
| params | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |
 | mapper | `Callable[[RawRow], Any]` | callable that receives a `RawRow` and returns a projected value. Mutually exclusive with `model`. | :thumbsup: | `None` |

`param=` remains accepted as a 1.x compatibility alias for `params=`. Pass only one of the two names.

{!docs/.parameter_shapes_read.md!}

{!docs/.row_mapping.md!}

## First, Single and Default
{!docs/.first_single_default.md!}

## Example
Execute a query and map the first result to a dataclass.
```python
{!docs/../docs_src/async_methods/query_single/example.py!}
```
(This script is complete, it should run "as is")
