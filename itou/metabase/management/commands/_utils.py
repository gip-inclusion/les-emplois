import logging
import os
from functools import lru_cache
from operator import attrgetter

from django.conf import settings
from django.utils import timezone
from django.utils.crypto import salted_hmac
from psycopg2 import sql

from itou.approvals.models import Approval
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS
from itou.job_applications.models import JobApplicationWorkflow
from itou.metabase.management.commands._database_psycopg2 import MetabaseDatabaseCursor
from itou.metabase.management.commands._database_tables import (
    get_dry_table_name,
    get_new_table_name,
    switch_table_atomically,
)
from itou.siaes.management.commands._import_siae.utils import timeit
from itou.siaes.models import Siae


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


def enable_sql_logging():
    # Unfortunately each SQL query log appears twice ¬_¬
    db_logger = logging.getLogger("django.db.backends")
    db_logger.setLevel(logging.DEBUG)
    db_logger.addHandler(logging.StreamHandler())


def convert_boolean_to_int(b):
    # True => 1, False => 0, None => None.
    return None if b is None else int(b)


def compose(f, g):
    # Compose two lambda methods.
    # https://stackoverflow.com/questions/16739290/composing-functions-in-python
    # I had to use this to solve a cryptic
    # `RecursionError: maximum recursion depth exceeded` error
    # when composing convert_boolean_to_int and c["fn"].
    return lambda *a, **kw: f(g(*a, **kw))


def get_choice(choices, key):
    choices = dict(choices)
    # Gettext fixes `can't adapt type '__proxy__'` error
    # due to laxy_gettext and psycopg2 not going well together.
    # See https://code.djangoproject.com/ticket/13965
    if key in choices:
        # FIXME: we dropped translations, this should be easier now.
        # return gettext(choices[key])
        return choices[key]
    return None


def chunks(items, n):
    """
    Yield successive n-sized chunks from items.
    """
    for i in range(0, len(items), n):
        yield items[i : i + n]


def anonymize(value, salt):
    """
    Use a salted hash to anonymize sensitive ids,
    mainly job_seeker id and job_application id.
    """
    return salted_hmac(salt, value, secret=settings.SECRET_KEY).hexdigest()


def get_first_membership_join_date(memberships):
    memberships = list(memberships.all())
    # We have to do all this in python to benefit from prefetch_related.
    if len(memberships) >= 1:
        memberships.sort(key=lambda o: o.joined_at)
        first_membership = memberships[0]
        return first_membership.joined_at
    return None


def get_hiring_siae(job_seeker):
    """
    Ideally the job_seeker would have a unique hiring so that we can
    properly link the approval back to the siae. However we already
    have many job_seekers with two or more hirings. In this case
    we consider the latest hiring, which is an ugly workaround
    around the fact that we do not have a proper approval=>siae
    link yet.
    """
    assert job_seeker.is_job_seeker
    hirings = [ja for ja in job_seeker.job_applications.all() if ja.state == JobApplicationWorkflow.STATE_ACCEPTED]
    if hirings:
        latest_hiring = max(hirings, key=attrgetter("created_at"))
        return latest_hiring.to_siae
    return None


def get_department_and_region_columns(name_suffix="", comment_suffix="", custom_fn=lambda o: o):
    return [
        {
            "name": f"département{name_suffix}",
            "type": "varchar",
            "comment": f"Département{comment_suffix}",
            "fn": lambda o: getattr(custom_fn(o), "department", None),
        },
        {
            "name": f"nom_département{name_suffix}",
            "type": "varchar",
            "comment": f"Nom complet du département{comment_suffix}",
            "fn": lambda o: DEPARTMENTS.get(getattr(custom_fn(o), "department", None)),
        },
        {
            "name": f"région{name_suffix}",
            "type": "varchar",
            "comment": f"Région{comment_suffix}",
            "fn": lambda o: DEPARTMENT_TO_REGION.get(getattr(custom_fn(o), "department", None)),
        },
    ]


def get_address_columns(name_suffix="", comment_suffix="", custom_fn=lambda o: o):
    return [
        {
            "name": f"adresse_ligne_1{name_suffix}",
            "type": "varchar",
            "comment": f"Première ligne adresse{comment_suffix}",
            "fn": lambda o: custom_fn(o).address_line_1,
        },
        {
            "name": f"adresse_ligne_2{name_suffix}",
            "type": "varchar",
            "comment": f"Seconde ligne adresse{comment_suffix}",
            "fn": lambda o: custom_fn(o).address_line_2,
        },
        {
            "name": f"code_postal{name_suffix}",
            "type": "varchar",
            "comment": f"Code postal{comment_suffix}",
            "fn": lambda o: custom_fn(o).post_code,
        },
        {
            "name": f"ville{name_suffix}",
            "type": "varchar",
            "comment": f"Ville{comment_suffix}",
            "fn": lambda o: custom_fn(o).city,
        },
    ] + get_department_and_region_columns(name_suffix, comment_suffix, custom_fn)


def get_establishment_last_login_date_column():
    return [
        {
            "name": "date_dernière_connexion",
            "type": "date",
            "comment": "Date de dernière connexion utilisateur",
            "fn": lambda o: max([u.last_login for u in o.members.all() if u.last_login], default=None)
            if o.members.exists()
            else None,
        },
    ]


def get_establishment_is_active_column():
    return [
        {
            "name": "active",
            "type": "boolean",
            "comment": "Dernière connexion dans les 7 jours",
            "fn": lambda o: any(
                [u.last_login > timezone.now() - timezone.timedelta(days=7) for u in o.members.all() if u.last_login]
            )
            if o.members.exists()
            else False,
        },
    ]


def _get_ai_stock_approvals():
    return Approval.objects.select_related("created_by").filter(
        created_by__email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL,
        created_at__date=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE.date(),
    )


@lru_cache(maxsize=1)
def get_ai_stock_approval_pks():
    """
    As of June 2022 we have exactly 71205 approvals from the AI stock and exactly the same number of job seekers.
    This number is supposed to stay constant over time, there is no reason for it to grow.
    We load all 71k pks once and for all in memory for performance reasons.
    """
    return _get_ai_stock_approvals().values_list("pk", flat=True).distinct()


@lru_cache(maxsize=1)
def get_ai_stock_job_seeker_pks():
    return _get_ai_stock_approvals().values_list("user_id", flat=True).distinct()


@lru_cache(maxsize=1)
def get_active_siae_pks():
    """
    Load once and for all the list of all active siae pks in memory and reuse them multiple times in various
    queries to avoid additional joins of the SiaeConvention model and the non trivial use of the
    `Siae.objects.active()` queryset on a related model of a queryset on another model. This is a list of less
    than 10k integers thus should not use much memory. The end result being both simpler code
    and better performance.
    """
    return [siae_pk for siae_pk in Siae.objects.active().values_list("pk", flat=True)]


def chunked_queryset(queryset, chunk_size=10000):
    """
    Slice a queryset into chunks. This is useful to avoid memory issues when
    iterating through large querysets.
    Credits go to:
    https://medium.com/@rui.jorge.rei/today-i-learned-django-memory-leak-and-the-sql-query-cache-1c152f62f64
    Code initially adapted from https://djangosnippets.org/snippets/10599/
    """
    if not queryset.exists():
        return
    queryset = queryset.order_by("pk")
    pks = queryset.values_list("pk", flat=True)
    start_pk = pks[0]
    while True:
        try:
            end_pk = pks.filter(pk__gte=start_pk)[chunk_size]
        except IndexError:
            break
        yield queryset.filter(pk__gte=start_pk, pk__lt=end_pk)
        start_pk = end_pk
    yield queryset.filter(pk__gte=start_pk)


@timeit
def build_custom_table(table_name, sql_request, dry_run):
    """
    Build a new table with given sql_request.
    Minimize downtime by building a temporary table first then swap the two tables atomically.
    """
    if dry_run:
        # Note that during a dry run, the dry run version of the current table will be built
        # from the wet run version of the underlying tables.
        table_name = get_dry_table_name(table_name)

    with MetabaseDatabaseCursor() as (cur, conn):
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(get_new_table_name(table_name))))
        conn.commit()
        cur.execute(
            sql.SQL("CREATE TABLE {} AS {}").format(
                sql.Identifier(get_new_table_name(table_name)), sql.SQL(sql_request)
            )
        )
        conn.commit()

    switch_table_atomically(table_name=table_name)


def build_final_tables(dry_run):
    """
    Build final custom tables one by one by playing SQL requests in `sql` folder.

    Typically:
    - 001_fluxIAE_DateDerniereMiseAJour.sql
    - 002_missions_ai_ehpad.sql
    - ...

    The numerical prefixes ensure the order of execution is deterministic.

    The name of the table being created with the query is derived from the filename,
    # e.g. '002_missions_ai_ehpad.sql' => 'missions_ai_ehpad'
    """
    path = f"{CURRENT_DIR}/sql"
    for filename in sorted([f for f in os.listdir(path) if f.endswith(".sql")]):
        print(f"Running {filename} ...")
        table_name = "_".join(filename.split(".")[0].split("_")[1:])
        with open(os.path.join(path, filename), "r") as file:
            sql_request = file.read()
        build_custom_table(table_name=table_name, sql_request=sql_request, dry_run=dry_run)
        print("Done.")


class MetabaseTable:
    def __init__(self, name):
        self.name = name
        self.columns = []

    def add_columns(self, columns):
        self.columns += columns

    def get(self, column_name, input):
        matching_columns = [c for c in self.columns if c["name"] == column_name]
        assert len(matching_columns) == 1
        fn = matching_columns[0]["fn"]
        return fn(input)
