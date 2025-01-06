import datetime

from django.utils import timezone


def convert_boolean_to_int(b):
    # True => 1, False => 0, None => None.
    return None if b is None else int(b)


def convert_datetime_to_local_date(dt):
    if isinstance(dt, datetime.datetime):
        # Datetimes are stored in UTC.
        return timezone.localdate(dt)
    return dt


def compose(f, g):
    # Compose two lambda methods.
    # https://stackoverflow.com/questions/16739290/composing-functions-in-python
    # I had to use this to solve a cryptic
    # `RecursionError: maximum recursion depth exceeded` error
    # when composing convert_boolean_to_int and c["fn"].
    return lambda *a, **kw: f(g(*a, **kw))


def chunked_queryset(queryset, chunk_size=10000):
    """
    Slice a queryset into chunks. This is useful to avoid memory issues when
    iterating through large querysets.
    Credits go to:
    https://medium.com/@rui.jorge.rei/today-i-learned-django-memory-leak-and-the-sql-query-cache-1c152f62f64
    Code initially adapted from https://djangosnippets.org/snippets/10599/
    """
    queryset = queryset.order_by("pk")
    pks = queryset.values_list("pk", flat=True)
    if not pks:
        return
    start_pk = pks[0]
    while True:
        try:
            end_pk = pks.filter(pk__gte=start_pk)[chunk_size]
        except IndexError:
            break
        yield queryset.filter(pk__gte=start_pk, pk__lt=end_pk)
        start_pk = end_pk
    yield queryset.filter(pk__gte=start_pk)
