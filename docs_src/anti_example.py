from psycopg2 import connect

with connect("postgresql://pydapper:pydapper@localhost/pydapper") as conn:
    with conn.cursor() as cursor:
        cursor.execute("select * from task")
        headers = [i[0] for i in cursor.description]
        data = cursor.fetchall()

list_data = [dict(zip(headers, row)) for row in data]
