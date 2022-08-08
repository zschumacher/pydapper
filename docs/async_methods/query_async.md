
`query_async` can execute a query and serialize the results to a model.

## Parameters
| name     | type        | description                                                                                   | optional     | default |
|----------|-------------|-----------------------------------------------------------------------------------------------|--------------|---------|
| sql      | `str`       | the sql query str to execute                                                                  | :thumbsdown: |         |
| param    | `ParamType` | params to substitute in the query                                                             | :thumbsup:   | `None`  |
 | model    | `Any`       | the callable to serialize the model;  callable must be able to accept column names as kwargs. | :thumbsup:   | `dict`  |
 | buffered | `bool`      | whether to buffer reading the results of the query                                            | :thumbsup:   | `True`  |


## Example - Serialize to a dataclass
The raw sql query can be executed using the `query_async` method and map the results to a list of dataclasses.
```python
{!docs/../docs_src/async_methods/query/basic_query.py!}
```
(*This script is complete, it should run "as is"*)


### Example - Serialize a one to one relationship
You can get creative with what you pass in to the model kwarg of `query`
```python
{!docs/../docs_src/async_methods/query/one_to_one_query.py!}
```
(This script is complete, it should run "as is")


### Example - Buffering queries
By default, `query` fetches all results and stores them in a list (buffered).  By setting `buffered=False`, you can
instead have `query` act as a generator function, fetching one record from the result set at a time.  This may be useful
if querying a large amount of data that would not fit into memory, but note that this keeps both the connection and
cursor open while you're retrieving results.
```python
{!docs/../docs_src/async_methods/query/query_unbuffered.py!}
```
(This script is complete, it should run "as is")


## Example - Serializing a one-to-many relationship
Using model is nice for simple serialization, but more complex serializations might require more complex logic.  In this
case, it is recommended to return an unbuffered result and serialize it as you iterate.  See the example below:
```python
{!docs/../docs_src/async_methods/query/one_to_many_query.py!}
```
(This script is complete, it should run "as is")
