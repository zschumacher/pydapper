 
`query_single` can execute a query and serialize the first result.  It throws an exception if there is not exactly one 
record in the result set.

## Parameters
| name  | type        | description                                                                                   | optional     | default |
|-------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql   | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
| param | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |

## First, Single and Default
{!docs/.first_single_default.md!}

## Example
Execute a query and map the first result to a dataclass.
```python
{!docs/../docs_src/methods/query_single/example.py!}
```
(This script is complete, it should run "as is")