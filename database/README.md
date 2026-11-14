# Database scripts

| File | Purpose |
|---|---|
| `setup_mysql.bat` | Recommended one-time setup: prompts (hidden) for the root password and a new app password, creates both databases and the user, saves the app password in `.env`, runs the DB check. |
| `create_database.sql` | One-time: creates `resqlens_db`, `resqlens_test` and the least-privilege user `resqlens_app`. Run as root (Workbench or `mysql -u root -p`). |
| `schema_mysql.sql` | Reference copy of the table definitions. **You do not need to run it**: the backend applies `backend/app/schema_mysql.sql` automatically (`CREATE TABLE IF NOT EXISTS`, never drops data). |
| `backup.bat` | Creates a timestamped dump in `database/backups/` with `mysqldump` (git-ignored). |

Restore a backup: `mysql -u root -p resqlens_db < database\backups\resqlens_db_YYYYMMDD_HHMM.sql`
