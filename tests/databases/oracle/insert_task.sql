BEGIN
    MERGE INTO pydapper.task t
    USING (
            SELECT 1 as id, 'Set up a test database' as description, TO_DATE('2021-12-31', 'YYYY-MM-DD') as due_date, 1 as owner_id FROM dual UNION ALL
            SELECT 2 as id, 'Seed the test database' as description, TO_DATE('2021-12-31', 'YYYY-MM-DD') as due_date, 1 as owner_id FROM dual UNION ALL
            SELECT 3 as id, 'Run the test suite' as description, TO_DATE('2022-01-01', 'YYYY-MM-DD') as due_date, 1 as owner_id FROM dual
    ) v ON (t.id = v.id)
    WHEN NOT MATCHED THEN INSERT (id, description, due_date, owner_id) VALUES (v.id, v.description, v.due_date, v.owner_id);
END;