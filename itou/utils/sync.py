import json

from django.db.models import QuerySet


def yield_sync_diff(
    collection: list[dict],
    collection_key: str,
    queryset: QuerySet,
    queryset_key: str,
    compared_keys: list[tuple[str, str]],
):
    """An utility function to yield human readable differences between:

    - a queryset that reflects the current state of a collection in the database
    - a new collection that is a list of dictionaries

    This function is thus handy as soon as we synchronize a DB collection with an external source of data.
    """
    label = queryset.model.__name__
    data_map = {c[collection_key]: c for c in collection}
    db_map = {getattr(obj, queryset_key): obj for obj in queryset.only(*[db_key for _, db_key in compared_keys])}

    coll_codes = set(data_map.keys())
    db_codes = set(queryset.values_list(queryset_key, flat=True))

    added_by_coll = coll_codes - db_codes
    already_there = coll_codes.intersection(db_codes)
    removed_in_coll = db_codes - coll_codes

    yield f"count={len(already_there)} label={label} had the same key in collection and queryset"
    for key in sorted(already_there):
        obj_db = db_map[key]
        obj_coll = data_map[key]
        for coll_key, db_key in compared_keys:
            db_val = getattr(obj_db, db_key)
            col_val = obj_coll[coll_key]
            if db_val != col_val:
                yield f"\tCHANGED {db_key}={db_val} changes to {coll_key}={col_val}"

    yield f"count={len(added_by_coll)} label={label} added by collection"
    for key in sorted(added_by_coll):
        obj_coll = data_map[key]
        yield f"\tADDED {json.dumps(obj_coll, ensure_ascii=False)}"

    yield f"count={len(removed_in_coll)} label={label} removed by collection"
    for key in sorted(removed_in_coll):
        yield f"\tREMOVED {db_map[key]}"
