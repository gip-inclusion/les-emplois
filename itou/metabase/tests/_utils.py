def get_fn_by_name(name, module):
    columns = module.TABLE_COLUMNS
    matching_columns = [c for c in columns if c["name"] == name]
    assert len(matching_columns) == 1
    fn = matching_columns[0]["fn"]
    return fn
