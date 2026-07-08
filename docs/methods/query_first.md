 
`query_first` can execute a query and map the first result.

## Parameters
| name  | type        | description                                                                                   | optional     | default |
|-------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql   | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
| params | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |

`param=` remains accepted as a 1.x compatibility alias for `params=`. Pass only one of the two names.

{!docs/.parameter_shapes_read.md!}

## First, Single and Default
{!docs/.first_single_default.md!}

## Example
Execute a query and map the first result to a dataclass.
```python
{!docs/../docs_src/methods/query_first/example.py!}
```
(This script is complete, it should run "as is")
