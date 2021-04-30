These custom SQL queries are run one by one at the end of the populate_metabase_fluxiae.py import.

The numerical prefix (001_, 002_...) is used to determine the exact order of execution.

The name of the table to be created using the given SQL query is extracted directly from the filename: e.g. `002_missions_ai_ehpad.sql` will create a `missions_ai_ehpad` table.