import functools
import hashlib
from operator import attrgetter

from django.conf import settings
from django.utils import timezone

from itou.approvals.models import Approval
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.models import Siae
from itou.users.models import User


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


@functools.cache
def get_post_code_to_insee_code_map():
    """
    Load once and for all this ~35k items dataset in memory.
    """
    post_code_to_insee_code_map = {}
    for city in City.objects.all():
        for post_code in city.post_codes:
            post_code_to_insee_code_map[post_code] = city.code_insee
    return post_code_to_insee_code_map


def convert_post_code_to_insee_code(post_code):
    return get_post_code_to_insee_code_map().get(post_code)


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
            "name": f"code_commune{name_suffix}",
            "type": "varchar",
            "comment": f"Code commune{comment_suffix}",
            "fn": lambda o: convert_post_code_to_insee_code(custom_fn(o).post_code),
        },
        {
            "name": f"ville{name_suffix}",
            "type": "varchar",
            "comment": f"Ville{comment_suffix}",
            "fn": lambda o: custom_fn(o).city,
        },
        {
            "name": f"longitude{name_suffix}",
            "type": "float",
            "comment": f"Longitude{comment_suffix}",
            "fn": lambda o: custom_fn(o).longitude,
        },
        {
            "name": f"latitude{name_suffix}",
            "type": "float",
            "comment": f"Latitude{comment_suffix}",
            "fn": lambda o: custom_fn(o).latitude,
        },
    ] + get_department_and_region_columns(name_suffix, comment_suffix, custom_fn)


def get_establishment_last_login_date_column():
    return [
        {
            "name": "date_dernière_connexion",
            "type": "date",
            "comment": "Date de dernière connexion utilisateur",
            "fn": lambda o: o.members_last_login,
        },
    ]


def get_establishment_is_active_column():
    return [
        {
            "name": "active",
            "type": "boolean",
            "comment": "Dernière connexion dans les 7 jours",
            "fn": lambda o: o.members_last_login > timezone.now() - timezone.timedelta(days=7)
            if o.members_last_login
            else False,
        },
    ]


def _get_ai_stock_approvals():
    return Approval.objects.select_related("created_by").filter(
        created_by__email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL,
        created_at__date=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE.date(),
    )


@functools.cache
def get_ai_stock_approval_pks():
    """
    As of June 2022 we have exactly 71205 approvals from the AI stock and exactly the same number of job seekers.
    This number is supposed to stay constant over time, there is no reason for it to grow.
    We load all 71k pks once and for all in memory for performance reasons.
    """
    return _get_ai_stock_approvals().values_list("pk", flat=True).distinct()


@functools.cache
def get_ai_stock_job_seeker_pks():
    return _get_ai_stock_approvals().values_list("user_id", flat=True).distinct()


@functools.cache
def get_active_siae_pks():
    """
    Load once and for all the list of all active siae pks in memory and reuse them multiple times in various
    queries to avoid additional joins of the SiaeConvention model and the non trivial use of the
    `Siae.objects.active()` queryset on a related model of a queryset on another model. This is a list of less
    than 10k integers thus should not use much memory. The end result being both simpler code
    and better performance.
    """
    return [siae_pk for siae_pk in Siae.objects.active().values_list("pk", flat=True)]


@functools.cache
def get_qpv_job_seeker_pks():
    """
    Load once and for all the list of all job seeker pks which are located in a QPV zone.

    The alternative would have been to naively compute `QPV.in_qpv(u, geom_field="coords")` for each and every one
    of the ~700k job seekers, which would have resulted in a undesirable deluge of 700k micro SQL requests.

    Unfortunately we failed so far at finding a clean ORM friendly way to do this in a single SQL request.
    """
    qpv_job_seekers = User.objects.raw(
        # Takes only ~2s on local dev.
        "SELECT uu.id FROM users_user uu INNER JOIN geo_qpv gq ON ST_Contains(gq.geometry, uu.coords::geometry)"
    )
    # A list of ~100k integers is permanently loaded in memory. It is fortunately not a very high volume of data.
    # Objects returned by `raw` are defered which means their fields are not preloaded unless they have been
    # explicitely specified in the SQL request. We did specify and thus preload `id` fields.
    return [job_seeker.pk for job_seeker in qpv_job_seekers]


def hash_content(content):
    return hashlib.sha256(f"{content}{settings.METABASE_HASH_SALT}".encode("utf-8")).hexdigest()
