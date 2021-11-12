"""
Helper methods for manipulating tables used by both populate_metabase_itou and populate_metabase_fluxiae scripts.
"""


def get_new_table_name(table_name):
    return f"{table_name}_new"


def get_old_table_name(table_name):
    return f"{table_name}_old"


def get_dry_table_name(table_name):
    return f"{table_name}_dry_run"
