import functools
import hashlib
from operator import attrgetter

from django.conf import settings
from django.db.models import JSONField
from django.db.models.fields import (
    AutoField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    PositiveIntegerField,
    TextField,
    UUIDField,
)
from django.db.models.fields.related import ForeignKey
from django.utils import timezone

from itou.approvals.enums import Origin, ProlongationReason
from itou.approvals.models import Approval
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS
from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE
from itou.companies.models import Company
from itou.geo.enums import ZRRStatus
from itou.geo.models import ZRR
from itou.job_applications.models import JobApplicationWorkflow
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


def get_field_type_from_field(field):
    if isinstance(field, CharField):
        return "varchar"
    if isinstance(field, TextField):
        return "text"
    if isinstance(field, PositiveIntegerField):
        return "integer"
    if isinstance(field, AutoField) and field.name == "id":
        return "integer"
    if isinstance(field, UUIDField):
        return "uuid"
    if isinstance(field, DateTimeField):
        return "timestamp with time zone"
    if isinstance(field, DateField):
        return "date"
    if isinstance(field, ForeignKey):
        related_pk_field = field.related_model._meta.pk
        return get_field_type_from_field(related_pk_field)
    if isinstance(field, JSONField):
        return "jsonb"
    if isinstance(field, BooleanField):
        return "boolean"
    raise ValueError("Unexpected field type")


def get_column_from_field(field, name):
    """
    Guess column configuration for simple fields with no subtlety.
    """
    field_name = field.name
    if isinstance(field, ForeignKey):
        field_name += "_id"
    return {
        "name": name,
        "type": get_field_type_from_field(field),
        "comment": field.verbose_name,
        "fn": lambda o: getattr(o, field_name),
    }


def get_choice(choices, key):
    choices = dict(choices)
    # Gettext fixes `can't adapt type '__proxy__'` error
    # due to laxy_gettext and psycopg not going well together.
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


def get_hiring_company(job_seeker):
    """
    Ideally the job_seeker would have a unique hiring so that we can
    properly link the approval back to the company. However we already
    have many job_seekers with two or more hirings. In this case
    we consider the latest hiring, which is an ugly workaround
    around the fact that we do not have a proper approval=>siae
    link yet.
    """
    assert job_seeker.is_job_seeker
    hirings = [ja for ja in job_seeker.job_applications.all() if ja.state == JobApplicationWorkflow.STATE_ACCEPTED]
    if hirings:
        latest_hiring = max(hirings, key=attrgetter("created_at"))
        return latest_hiring.to_company
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


# FIXME @dejafait drop this as soon as data analysts no longer use
# structures_v0.code_commune nor organisations.code_commune
# because one post_code can actually have *several* insee_codes (╯°□°)╯︵ ┻━┻
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


# FIXME @dejafait drop this as soon as data analysts no longer use
# structures_v0.code_commune nor organisations.code_commune
# because one post_code can actually have *several* insee_codes (╯°□°)╯︵ ┻━┻
def convert_post_code_to_insee_code(post_code):
    return get_post_code_to_insee_code_map().get(post_code)


@functools.cache
def get_insee_code_to_zrr_status_map():
    """
    Load once and for all this ~35k items dataset in memory.
    """
    insee_code_to_zrr_status_map = {}
    for zrr in ZRR.objects.all():
        insee_code_to_zrr_status_map[zrr.insee_code] = zrr.status
    return insee_code_to_zrr_status_map


def get_zrr_status_for_insee_code(insee_code):
    raw_zrr_status = get_insee_code_to_zrr_status_map().get(insee_code)
    if raw_zrr_status:
        return ZRRStatus(raw_zrr_status).label
    return "Statut ZRR inconnu"


def get_post_code_column(name_suffix="", comment_suffix="", custom_fn=lambda o: o):
    return {
        "name": f"code_postal{name_suffix}",
        "type": "varchar",
        "comment": f"Code postal{comment_suffix}",
        "fn": lambda o: custom_fn(o).post_code,
    }


def get_address_columns(name_suffix="", comment_suffix="", custom_fn=lambda o: o):
    return (
        [
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
        ]
        + [get_post_code_column(name_suffix, comment_suffix, custom_fn)]
        + [
            {
                # FIXME @dejafait drop this as soon as data analysts no longer use
                # structures_v0.code_commune nor organisations.code_commune
                # because one post_code can actually have *several* insee_codes (╯°□°)╯︵ ┻━┻
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
                "type": "double precision",
                "comment": f"Longitude{comment_suffix}",
                "fn": lambda o: custom_fn(o).longitude,
            },
            {
                "name": f"latitude{name_suffix}",
                "type": "double precision",
                "comment": f"Latitude{comment_suffix}",
                "fn": lambda o: custom_fn(o).latitude,
            },
        ]
        + get_department_and_region_columns(name_suffix, comment_suffix, custom_fn)
    )


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


@functools.cache
def get_ai_stock_job_seeker_pks():
    return Approval.objects.filter(origin=Origin.AI_STOCK).values_list("user_id", flat=True).distinct()


@functools.cache
def get_active_companies_pks():
    """
    Load once and for all the list of all active company pks in memory and reuse them multiple times in various
    queries to avoid additional joins of the SiaeConvention model and the non trivial use of the
    `Company.objects.active()` queryset on a related model of a queryset on another model. This is a list of less
    than 10k integers thus should not use much memory. The end result being both simpler code
    and better performance.
    """
    return list(Company.objects.active().values_list("pk", flat=True))


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
        "SELECT uu.id FROM users_user uu "
        "INNER JOIN geo_qpv gq ON ST_Contains(gq.geometry, uu.coords::geometry) "
        f"WHERE uu.coords IS NOT NULL AND uu.geocoding_score > {BAN_API_RELIANCE_SCORE}"
    )
    # A list of ~100k integers is permanently loaded in memory. It is fortunately not a very high volume of data.
    # Objects returned by `raw` are defered which means their fields are not preloaded unless they have been
    # explicitely specified in the SQL request. We did specify and thus preload `id` fields.
    return [job_seeker.pk for job_seeker in qpv_job_seekers]


def hash_content(content):
    return hashlib.sha256(f"{content}{settings.METABASE_HASH_SALT}".encode()).hexdigest()


def get_common_prolongation_columns(get_field_fn):
    return [
        get_column_from_field(get_field_fn("id"), name="id"),
        get_column_from_field(get_field_fn("approval"), name="id_pass_agrément"),
        get_column_from_field(get_field_fn("start_at"), name="date_début"),
        get_column_from_field(get_field_fn("end_at"), name="date_fin"),
        {
            "name": "motif",
            "type": "varchar",
            "comment": "Motif renseigné",
            "fn": lambda o: get_choice(choices=ProlongationReason.choices, key=o.reason),
        },
        # Do not inject `reason_explanation` as it contains highly sensitive personal information in practice.
        get_column_from_field(get_field_fn("declared_by"), name="id_utilisateur_déclarant"),
        get_column_from_field(get_field_fn("declared_by_siae"), name="id_structure_déclarante"),
        get_column_from_field(get_field_fn("validated_by"), name="id_utilisateur_prescripteur"),
        get_column_from_field(get_field_fn("prescriber_organization"), name="id_organisation_prescripteur"),
    ]
