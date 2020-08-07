# This "WIP" mode is useful for quickly testing changes and iterating.
# It builds tables with a *_wip suffix added to their name, to avoid
# touching any real table, and injects only a sample of data.
ENABLE_WIP_MODE = True
WIP_MODE_ROWS_PER_TABLE = 100

# Useful to troobleshoot whether this scripts runs a deluge of SQL requests.
SHOW_SQL_REQUESTS = False

if ENABLE_WIP_MODE:
    MAX_ROWS_PER_TABLE = WIP_MODE_ROWS_PER_TABLE
else:
    # Clumsy way to set an infinite number.
    # Makes the code using this constant much simpler to read.
    MAX_ROWS_PER_TABLE = 1000 * 1000 * 1000

# Set how many rows are inserted at a time in metabase database.
# -- Bench results for self.populate_approvals()
# by batch of 100 => 2m38s
# by batch of 1000 => 2m23s
# -- Bench results for self.populate_diagnostics()
# by batch of 1 => 2m51s
# by batch of 10 => 19s
# by batch of 100 => 5s
# by batch of 1000 => 5s
INSERT_BATCH_SIZE = 1000
