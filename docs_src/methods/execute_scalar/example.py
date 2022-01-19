from pydapper import connect

with connect("postgresql://pydapper:pydapper@localhost/pydapper") as commands:
    owner_name = commands.execute_scalar("select name from owner")

print(owner_name)
# Zach Schumacher
