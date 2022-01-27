# [MySQL](https://www.mysql.com/)
Supported drivers:

| dbapi                                                                    | default    | driver        | connection class                                   |
|--------------------------------------------------------------------------|------------|---------------|----------------------------------------------------|
| [mysql-connector-python](https://dev.mysql.com/doc/connector-python/en/) | :thumbsup: | `mysql+mysql` | `mysql.connector.connection_cext.CMySQLConnection` |

## mysql-connector-python
`mysql-connector-python` is the default dbapi driver for MySQL in *pydapper*.

### Example - `connect`
The [mysql-connector-python docs](https://github.com/mysql/mysql-connector-python/blob/90eaeca65a6bbfc1fd9218aad5303957798215c3/lib/mysql/connector/abstracts.py#L142) 
do not have clear examples of the behavior of the context manager.  For the current version, the context manager 
simply closes the connection when it is finished.  Handling transactions commits is up to you (see example).
```python
{!docs/../docs_src/connections/mysql_connector_python_connect.py!}
```

### Example - `using`
Use *pydapper* with a `mysql-connector-python` connection pool.
```python
{!docs/../docs_src/connections/mysql_connector_python_using.py!}
```
