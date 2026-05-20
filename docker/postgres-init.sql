-- Runs once on a fresh Postgres volume (Postgres image executes any *.sql
-- in /docker-entrypoint-initdb.d/ on first boot). The dev DB itself
-- is created by Postgres from POSTGRES_DB, so we only need to add the
-- companion test DB here.
--
-- If you wipe pgdata after this file was added, both DBs will be present
-- automatically. For an EXISTING volume that never saw this script, run
--   make ensure-test-db
-- to CREATE DATABASE docstore_test manually (the make target is idempotent).

CREATE DATABASE docstore_test OWNER docstore;
