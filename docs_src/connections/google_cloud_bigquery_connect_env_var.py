import pydapper

# export GOOGLE_APPLICATION_CREDENTIALS=/path/to/keystore.json

with pydapper.connect("bigquery+google:////") as commands:
    print(type(commands))
    # <class 'pydapper.bigquery.google_bigquery_client.GoogleBigqueryClientCommands'>

    print(type(commands.connection))
    # <class 'google.cloud.bigquery.dbapi.connection.Connection'>

    raw_cursor = commands.cursor()
    print(type(raw_cursor))
    # <class 'google.cloud.bigquery.dbapi.cursor.Cursor'>
