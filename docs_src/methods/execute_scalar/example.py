from pydapper import connect

with connect() as commands:
    owner_name = commands.execute_scalar("select name from owner")

print(owner_name)
# Zach Schumacher
