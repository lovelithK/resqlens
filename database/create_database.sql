-- ResQLens – one-time MySQL setup (run as root or another admin account).
--
-- MySQL Workbench: open the "ResQLens Local" (root) connection, File > Open SQL Script,
--   choose this file, REPLACE the password placeholder below, then Execute (lightning icon).
-- Command line (prompts for the root password, nothing is stored):
--   mysql -u root -p < database\create_database.sql
--
-- Only the database and a least-privilege application user are created here.
-- The tables are created automatically by the backend on first start
-- (backend/app/schema_mysql.sql), so there is exactly one schema definition.

CREATE DATABASE IF NOT EXISTS resqlens_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Disposable database used only by the automated tests (TEST_DB_ENGINE=mysql)
CREATE DATABASE IF NOT EXISTS resqlens_test
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- >>> Replace CHANGE_ME_Strong_Password_1 with your own password, and put the
-- >>> same value in DB_PASSWORD in the project's .env file.
CREATE USER IF NOT EXISTS 'resqlens_app'@'localhost' IDENTIFIED BY 'CHANGE_ME_Strong_Password_1';
CREATE USER IF NOT EXISTS 'resqlens_app'@'127.0.0.1' IDENTIFIED BY 'CHANGE_ME_Strong_Password_1';

-- Least privilege: data + schema-creation rights on resqlens_db only (no DROP, no GRANT, no global rights).
-- DROP is granted only on the disposable test database, which the test-suite empties before each run.
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
  ON resqlens_db.* TO 'resqlens_app'@'localhost', 'resqlens_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP
  ON resqlens_test.* TO 'resqlens_app'@'localhost', 'resqlens_app'@'127.0.0.1';
FLUSH PRIVILEGES;

SHOW GRANTS FOR 'resqlens_app'@'localhost';
