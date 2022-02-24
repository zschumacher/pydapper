
`execute_async` can execute a command one or multiple times and return the number of affected rows. This method is usually used
to execute insert, update or delete operations.

## Parameters
| name  | type                       | description                       | optional     | default |
|-------|----------------------------|-----------------------------------|--------------|---------|
 | sql   | `str`                      | the sql query str to execute      | :thumbsdown: |         |
 | param | `ListParamType, ParamType` | params to substitute in the query | :thumbsup:   | `None`  |

## Example - Execute Insert
### Single
Execute the INSERT statement a single time.

```python
{!docs/../docs_src/async_methods/execute/insert_single.py!}
```
(*This script is complete, it should run "as is"*)

### Multiple
Execute the INSERT statement multiple times, one for each object in the param list.

```python
{!docs/../docs_src/async_methods/execute/insert_multiple.py!}
```
(*This script is complete, it should run "as is"*)

## Example - Execute Update
### Single
Execute the UPDATE statement a single time.

```python
{!docs/../docs_src/async_methods/execute/update_single.py!}
```
(*This script is complete, it should run "as is"*)

### Multiple
Execute the UPDATE statement multiple times, one for each object in the param list.

```python
{!docs/../docs_src/async_methods/execute/update_multiple.py!}
```
(*This script is complete, it should run "as is"*)

## Example - Execute Delete
### Single
Execute the DELETE statement a single time.

```python
{!docs/../docs_src/async_methods/execute/delete_single.py!}
```
(*This script is complete, it should run "as is"*)

### Multiple
Execute the DELETE statement multiple times, one for each object in the param list.

```python
{!docs/../docs_src/async_methods/execute/delete_multiple.py!}
```
(*This script is complete, it should run "as is"*)
