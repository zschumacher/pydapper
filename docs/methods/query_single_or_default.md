 
`query_single_or_default` can execute a query and serialize the first result, or return a default value if the result
set is empty; this method throws an exception if there is more than one element in the result set.

## Parameters
| name    | type        | description                                                                                   | optional     | default |
|---------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql     | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
 | default | `Any`       | any object to return if the result set is empty                                               | :thumbsdown: |
| param   | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model   | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |


## First, Single and Default
{!docs/.first_single_default.md!}

## Example
Execute a query and map the result to a dataclass.
```python
{!docs/../docs_src/methods/query_single_or_default/example.py!}
```
(This script is complete, it should run "as is")