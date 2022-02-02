BEGIN
    MERGE INTO pydapper.owner o USING (SELECT 1 as id, 'Zach Schumacher' as name FROM dual) v
    ON (o.id = v.id)
    WHEN NOT MATCHED THEN INSERT (id, name) VALUES (v.id, v.name);
END;