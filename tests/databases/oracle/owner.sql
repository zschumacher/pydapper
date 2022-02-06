BEGIN
    EXECUTE IMMEDIATE '
        CREATE TABLE pydapper.owner (
            id NUMBER GENERATED BY DEFAULT AS IDENTITY,
            name VARCHAR(255) NOT NULL,

            PRIMARY KEY (id)
        )';
    EXCEPTION
        WHEN OTHERS THEN IF SQLCODE = -955 THEN NULL; ELSE RAISE; END IF;
END;