# [MySQL](https://www.mysql.com/)
Supported drivers:

| dbapi                                                                    | default    | driver        | connection class                                   |
|--------------------------------------------------------------------------|------------|---------------|----------------------------------------------------|
| [mysql-connector-python](https://dev.mysql.com/doc/connector-python/en/) | :thumbsup: | `mysql+mysql` | `mysql.connector.connection_cext.CMySQLConnection` |

## mysql-connector-python
`mysql-connector-python` is the default dbapi driver for MySQL in *pydapper*.  It is actually registered as `mysql`
because that is the name of the actual package that is installed.

!!! note
    Because of the build in behavior of `mysql-connector-python`, it is currently required to run `cursor.fetchall()`
    in the `query_first` implementation in order to flush the result set from the server 
    When using `query_first` with MySQL, it is advisable to use `LIMIT 1` in your query to prevent downloading
    unneeded rows.

### Installation
=== "pip"
    ```console
    pip install pydapper[mysql-connector-python]
    ```

=== "poetry"
    ```console
    poetry add pydapper -E mysql-connector-python
    ```

### DSN format
=== "Template"
    ```python
    dsn = f"mysql+mysql://{user}:{password}@{host}:{port}/{dbname}"
    ```

=== "Example"
    ```python
    dsn = "mysql+mysql://myuser:mypassword:3306@localhost/mydb"
    ```

=== "Example (Default Driver)"
    ```python
    dsn = "mysql://myuser:mypassword:3306@localhost/mydb"
    ```

!!! note
    Databases and schemas are synonymous in MySQL.

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


