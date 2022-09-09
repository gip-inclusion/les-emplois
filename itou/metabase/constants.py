METABASE_SHOW_SQL_REQUESTS = False


METABASE_DRY_RUN_ROWS_PER_QUERYSET = 1000

# Set how many rows are inserted at a time in metabase database.
# A bigger number makes the script faster until a certain point,
# but it also increases RAM usage.
# -- Bench results for self.populate_approvals()
# by batch of 100 => 2m38s
# by batch of 1000 => 2m23s
# -- Bench results for self.populate_diagnostics()
# by batch of 1 => 2m51s
# by batch of 10 => 19s
# by batch of 100 => 5s
# by batch of 1000 => 5s
METABASE_INSERT_BATCH_SIZE = 100
