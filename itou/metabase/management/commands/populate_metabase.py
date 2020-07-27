"""
Populate metabase database with transformed data from itou database.

This script reads data from the itou production database,
transforms it for the convenience of our metabase non tech-savvy,
french speaking only users, and injects the result into metabase.

The itou production database is never modified, only read.

The metabase database tables are trashed and recreated every time.

The data is heavily denormalized among tables so that the metabase user
has all the fields needed and thus never needs to perform joining two tables.

We maintain a google sheet with extensive documentation about all tables
and fields. Not linked here but easy to find internally.
"""
import logging
import random
from datetime import date, datetime, timedelta, timezone
from functools import partial

import psycopg2
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext, gettext_lazy as _
from tqdm import tqdm

from itou.approvals.models import Approval, PoleEmploiApproval
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS


# This "WIP" mode is useful for quickly testing changes and iterating.
# It builds tables with a *_wip suffix added to their name, to avoid
# touching any real table, and injects only a sample of data.
ENABLE_WIP_MODE = False
WIP_MODE_ROWS_PER_TABLE = 1000

# Useful to troobleshoot whether this scripts runs a deluge of SQL requests.
SHOW_SQL_REQUESTS = False

if ENABLE_WIP_MODE:
    MAX_ROWS_PER_TABLE = WIP_MODE_ROWS_PER_TABLE
else:
    # Clumsy way to set an infinite number.
    # Makes the code using this constant much simpler to read.
    MAX_ROWS_PER_TABLE = 1000 * 1000 * 1000

if SHOW_SQL_REQUESTS:
    # Unfortunately each SQL query log appears twice ¬_¬
    mylogger = logging.getLogger("django.db.backends")
    mylogger.setLevel(logging.DEBUG)
    mylogger.addHandler(logging.StreamHandler())

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

POLE_EMPLOI_APPROVAL_MINIMUM_START_DATE = datetime(2018, 1, 1)

# Reword the original JobApplication.SENDER_KIND_CHOICES
SENDER_KIND_CHOICES = (
    (JobApplication.SENDER_KIND_JOB_SEEKER, _("Candidature autonome")),
    (JobApplication.SENDER_KIND_PRESCRIBER, _("Candidature via prescripteur")),
    (JobApplication.SENDER_KIND_SIAE_STAFF, _("Auto-prescription")),
)

# Reword the original EligibilityDiagnosis.AUTHOR_KIND_CHOICES
AUTHOR_KIND_CHOICES = (
    (EligibilityDiagnosis.AUTHOR_KIND_JOB_SEEKER, _("Demandeur d'emploi")),
    (EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER, _("Prescripteur")),
    (EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF, _("Employeur")),
)

# Special fake adhoc organization designed to gather stats
# of all prescriber accounts without organization.
# Otherwise organization stats would miss those accounts
# contribution.
# Of course this organization is *never* actually saved in itou's db.
ORG_OF_PRESCRIBERS_WITHOUT_ORG = PrescriberOrganization(
    id=-1, name="Regroupement des prescripteurs sans organisation", kind="SANS-ORGANISATION", is_authorized=False
)

# Preload association for best performance and to avoid having to make
# PoleEmploiApproval.pe_structure_code a foreign key.
CODE_SAFIR_TO_PE_ORG = {
    org.code_safir_pole_emploi: org
    for org in PrescriberOrganization.objects.filter(code_safir_pole_emploi__isnull=False).all()
}


def anonymize(value, salt):
    """
    Use a salted hash to anonymize sensitive ids,
    mainly job_seeker id and job_application id.
    """
    return salted_hmac(salt, value, secret=settings.SECRET_KEY).hexdigest()


def chunks(l, n):
    """
    Yield successive n-sized chunks from l.
    """
    for i in range(0, len(l), n):
        yield l[i : i + n]


def get_choice(choices, key):
    choices = dict(choices)
    # Gettext fixes `can't adapt type '__proxy__'` error
    # due to laxy_gettext and psycopg2 not going well together.
    # See https://code.djangoproject.com/ticket/13965
    if key in choices:
        return gettext(choices[key])
    return None


def _get_first_membership_join_date(memberships):
    memberships = list(memberships.all())
    # We have to do all this in python to benefit from prefetch_related.
    if len(memberships) >= 1:
        memberships.sort(key=lambda o: o.joined_at)
        first_membership = memberships[0]
        return first_membership.joined_at
    return None


def get_siae_first_join_date(siae):
    return _get_first_membership_join_date(memberships=siae.siaemembership_set)


def get_org_first_join_date(org):
    if org != ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        return _get_first_membership_join_date(memberships=org.prescribermembership_set)
    return None


def get_org_members_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        # Number of prescriber users without org.
        return get_user_model().objects.filter(is_prescriber=True, prescribermembership=None).count()
    return org.members.count()


def get_org_job_applications_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        # Number of job applications made by prescribers without org.
        return JobApplication.objects.filter(
            sender_kind=JobApplication.SENDER_KIND_PRESCRIBER, sender_prescriber_organization=None
        ).count()
    return org.jobapplication_set.count()


def get_org_accepted_job_applications_count(org):
    if org == ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        return JobApplication.objects.filter(
            sender_kind=JobApplication.SENDER_KIND_PRESCRIBER,
            sender_prescriber_organization=None,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
        ).count()
    job_applications = list(org.jobapplication_set.all())
    # We have to do all this in python to benefit from prefetch_related.
    return len([ja for ja in job_applications if ja.state == JobApplicationWorkflow.STATE_ACCEPTED])


def get_job_application_sub_type(ja):
    """
    Builds a human readable sub category for job applications, e.g.
    - Auto-prescription ACI
    - Auto-prescription ETTI
    - Candidature via prescripteur PE
    - Candidature via prescripteur ML
    - Candidature via prescripteur sans organisation
    - Candidature autonome
    """
    # Start with the regular type.
    sub_type = get_choice(choices=SENDER_KIND_CHOICES, key=ja.sender_kind)
    # Add the relevant sub type depending on the type.
    if ja.sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF:
        sub_type += f" {ja.sender_siae.kind}"
    if ja.sender_kind == JobApplication.SENDER_KIND_PRESCRIBER:
        if ja.sender_prescriber_organization:
            sub_type += f" {ja.sender_prescriber_organization.kind}"
        else:
            sub_type += f" sans organisation"
    return sub_type


def _get_ja_time_spent_in_transition(ja, logs):
    if len(logs) >= 1:
        assert len(logs) == 1
        new_timestamp = ja.created_at
        transition_timestamp = logs[0].timestamp
        assert transition_timestamp > new_timestamp
        time_spent_in_transition = transition_timestamp - new_timestamp
        return time_spent_in_transition
    return None


def get_ja_time_spent_from_new_to_processing(ja):
    # Find the new=>processing transition log.
    # We have to do all this in python to benefit from prefetch_related.
    logs = [l for l in ja.logs.all() if l.transition == JobApplicationWorkflow.TRANSITION_PROCESS]
    return _get_ja_time_spent_in_transition(ja, logs)


def get_ja_time_spent_from_new_to_accepted_or_refused(ja):
    # Find the *=>accepted or *=>refused transition log.
    # We have to do all this in python to benefit from prefetch_related.
    logs = [
        l
        for l in ja.logs.all()
        if l.to_state in [JobApplicationWorkflow.STATE_ACCEPTED, JobApplicationWorkflow.STATE_REFUSED]
    ]
    return _get_ja_time_spent_in_transition(ja, logs)


def get_timedelta_since_org_last_job_application(org):
    if org != ORG_OF_PRESCRIBERS_WITHOUT_ORG:
        job_applications = list(org.jobapplication_set.all())
        # We have to do all this in python to benefit from prefetch_related.
        if len(job_applications) >= 1:
            job_applications.sort(key=lambda o: o.created_at, reverse=True)
            last_job_application = job_applications[0]
            now = datetime.now(timezone.utc)
            return now - last_job_application.created_at
    # This field makes no sense for prescribers without org.
    return None


def get_user_age_in_years(user):
    if user.birthdate:
        return date.today().year - user.birthdate.year
    return None


def get_job_seeker_id_to_latest_diagnosis():
    """
    Preload this association once and for all for best performance.
    """
    # Order by created_at so that most recent diagnoses overrides older ones.
    diagnoses = (
        EligibilityDiagnosis.objects.order_by("created_at")
        .select_related("author_siae", "author_prescriber_organization")
        .prefetch_related("administrative_criteria")
    )
    job_seeker_id_to_latest_diagnosis = {}
    for diagnosis in diagnoses:
        job_seeker_id = diagnosis.job_seeker_id
        job_seeker_id_to_latest_diagnosis[job_seeker_id] = diagnosis
    return job_seeker_id_to_latest_diagnosis


JOB_SEEKER_ID_TO_LATEST_DIAGNOSIS = get_job_seeker_id_to_latest_diagnosis()


def get_latest_diagnosis(job_seeker):
    assert job_seeker.is_job_seeker
    return JOB_SEEKER_ID_TO_LATEST_DIAGNOSIS.get(job_seeker.id)


def get_latest_diagnosis_author_sub_kind(job_seeker):
    """
    Build a human readable sub category, e.g.
    - Employeur ACI
    - Employeur ETTI
    - Prescripteur PE
    - Prescripteur ML
    """
    latest_diagnosis = get_latest_diagnosis(job_seeker)
    if latest_diagnosis:
        author_kind = get_choice(choices=AUTHOR_KIND_CHOICES, key=latest_diagnosis.author_kind)
        if latest_diagnosis.author_kind == EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF:
            author_sub_kind = latest_diagnosis.author_siae.kind
        elif latest_diagnosis.author_kind == EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER:
            author_sub_kind = latest_diagnosis.author_prescriber_organization.kind
        else:
            raise ValueError("Unexpected latest_diagnosis.author_kind")
        return f"{author_kind} {author_sub_kind}"
    return None


def _get_latest_diagnosis_criteria_by_level(job_seeker, level):
    """
    Count criteria of given level for the latest diagnosis of
    given job seeker.
    """
    latest_diagnosis = get_latest_diagnosis(job_seeker)
    if latest_diagnosis:
        # We have to do all this in python to benefit from prefetch_related.
        return len([ac for ac in latest_diagnosis.administrative_criteria.all() if ac.level == level])
    return None


def get_latest_diagnosis_level1_criteria(job_seeker):
    return _get_latest_diagnosis_criteria_by_level(job_seeker=job_seeker, level=AdministrativeCriteria.Level.LEVEL_1)


def get_latest_diagnosis_level2_criteria(job_seeker):
    return _get_latest_diagnosis_criteria_by_level(job_seeker=job_seeker, level=AdministrativeCriteria.Level.LEVEL_2)


def get_latest_diagnosis_criteria(job_seeker, criteria_id):
    """
    Check if given criteria_id is actually present in latest diagnosis
    of given job seeker.
    """
    latest_diagnosis = get_latest_diagnosis(job_seeker)
    if latest_diagnosis:
        # We have to do all this in python to benefit from prefetch_related.
        return len([ac for ac in latest_diagnosis.administrative_criteria.all() if ac.id == criteria_id])
    return None


def convert_boolean_to_int(b):
    # True => 1, False => 0, None => None.
    return None if b is None else int(b)


def compose(f, g):
    # Compose two lambda methods.
    # https://stackoverflow.com/questions/16739290/composing-functions-in-python
    # I had to use this to solve a cryptic
    # `RecursionError: maximum recursion depth exceeded` error
    # when composing convert_boolean_to_int and c["lambda"].
    return lambda *a, **kw: f(g(*a, **kw))


POLE_EMPLOI_APPROVAL_SUFFIX_TO_MEANING = {
    "P": "Prolongation",
    "E": "Extension",
    "A": "Interruption",
    "S": "Suspension",
}


def get_approval_type(approval):
    """
    Build a human readable category for approvals and PE approvals.
    """
    if isinstance(approval, Approval):
        if approval.number.startswith("99999"):
            return "Pass IAE (99999)"
        else:
            return "Agrément PE via ITOU (non 99999)"
    elif isinstance(approval, PoleEmploiApproval):
        if len(approval.number) == 12:
            return "Agrément PE"
        elif len(approval.number) == 15:
            suffix = approval.number[12]
            return f"{POLE_EMPLOI_APPROVAL_SUFFIX_TO_MEANING[suffix]} PE"
        else:
            raise ValueError("Unexpected PoleEmploiApproval.number length")
    else:
        raise ValueError("Unknown approval type.")


def get_job_seeker_id_to_hiring_siae():
    """
    Ideally the job_seeker would have a unique hiring so that we can
    properly link the approval back to the siae. However we already
    have many job_seekers with two or more hirings. In this case
    we consider the latest hiring, which is an ugly workaround
    around the issue that we do not have a proper approval=>siae
    link yet.

    Preload this association data for best performance.
    """
    # Order by created_at so that most recent hiring overrides older ones.
    hirings = (
        JobApplication.objects.filter(state=JobApplicationWorkflow.STATE_ACCEPTED)
        .order_by("created_at")
        .select_related("to_siae")
    )
    job_seeker_id_to_hiring_siae = {}
    for hiring in hirings:
        job_seeker_id = hiring.job_seeker_id
        job_seeker_id_to_hiring_siae[job_seeker_id] = hiring.to_siae
    return job_seeker_id_to_hiring_siae


JOB_SEEKER_ID_TO_HIRING_SIAE = get_job_seeker_id_to_hiring_siae()


def get_siae_from_approval(approval):
    if isinstance(approval, PoleEmploiApproval):
        return None
    assert isinstance(approval, Approval)
    return JOB_SEEKER_ID_TO_HIRING_SIAE.get(approval.user_id)


def get_siae_or_pe_org_from_approval(approval):
    if isinstance(approval, Approval):
        return get_siae_from_approval(approval)
    assert isinstance(approval, PoleEmploiApproval)
    code_safir = approval.pe_structure_code
    pe_org = CODE_SAFIR_TO_PE_ORG.get(code_safir)
    return pe_org


class MetabaseDatabaseCursor:
    def __enter__(self):
        self.conn = psycopg2.connect(
            host=settings.METABASE_HOST,
            port=settings.METABASE_PORT,
            dbname=settings.METABASE_DATABASE,
            user=settings.METABASE_USER,
            password=settings.METABASE_PASSWORD,
        )
        self.cur = self.conn.cursor()
        return self.cur

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.conn.commit()
        self.cur.close()
        self.conn.close()


def get_address_columns(name_suffix="", comment_suffix=""):
    return [
        {
            "name": f"adresse_ligne_1{name_suffix}",
            "type": "varchar",
            "comment": f"Première ligne adresse{comment_suffix}",
            "lambda": lambda o: o.address_line_1,
        },
        {
            "name": f"adresse_ligne_2{name_suffix}",
            "type": "varchar",
            "comment": f"Seconde ligne adresse{comment_suffix}",
            "lambda": lambda o: o.address_line_2,
        },
        {
            "name": f"code_postal{name_suffix}",
            "type": "varchar",
            "comment": f"Code postal{comment_suffix}",
            "lambda": lambda o: o.post_code,
        },
        {
            "name": f"ville{name_suffix}",
            "type": "varchar",
            "comment": f"Ville{comment_suffix}",
            "lambda": lambda o: o.city,
        },
    ] + get_department_and_region_columns(name_suffix, comment_suffix)


def get_department_and_region_columns(name_suffix="", comment_suffix="", custom_lambda=lambda o: o):
    return [
        {
            "name": f"département{name_suffix}",
            "type": "varchar",
            "comment": f"Département{comment_suffix}",
            "lambda": lambda o: custom_lambda(o).department if custom_lambda(o) else None,
        },
        {
            "name": f"nom_département{name_suffix}",
            "type": "varchar",
            "comment": f"Nom complet du département{comment_suffix}",
            "lambda": lambda o: DEPARTMENTS.get(custom_lambda(o).department) if custom_lambda(o) else None,
        },
        {
            "name": f"région{name_suffix}",
            "type": "varchar",
            "comment": f"Région{comment_suffix}",
            "lambda": lambda o: DEPARTMENT_TO_REGION.get(custom_lambda(o).department) if custom_lambda(o) else None,
        },
    ]


class Command(BaseCommand):
    """
    Populate metabase database.

    No dry run is available for this script.
    Use ENABLE_WIP_MODE instead.

    How to run:
        $ django-admin populate_metabase --verbosity=2
    """

    help = "Populate metabase database."

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def log(self, message):
        self.logger.debug(message)

    def cleanup_tables(self, table_name):
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_new;")
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_old;")
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_wip;")
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_wip_new;")
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_wip_old;")

    def populate_table(self, table_name, table_columns, objects):
        """
        Generic method to populate each table.
        Create table with a temporary name, add column comments,
        inject content and finally swap with the target table.
        """
        self.cleanup_tables(table_name)

        if ENABLE_WIP_MODE:
            table_name = f"{table_name}_wip"
            objects = random.sample(list(objects), MAX_ROWS_PER_TABLE)

        # Transform boolean fields into 0-1 integer fields as
        # metabase cannot sum or average boolean columns ¯\_(ツ)_/¯
        for c in table_columns:
            if c["type"] == "boolean":
                c["type"] = "integer"
                c["lambda"] = compose(convert_boolean_to_int, c["lambda"])

        self.log(f"Injecting {len(objects)} rows with {len(table_columns)} columns into table {table_name}:")

        # Create table.
        statement = ", ".join([f'{c["name"]} {c["type"]}' for c in table_columns])
        self.cur.execute(f"CREATE TABLE {table_name}_new ({statement});")

        # Add comments on table columns.
        for c in table_columns:
            assert set(c.keys()) == set(["name", "type", "comment", "lambda"])
            column_name = c["name"]
            column_comment = c["comment"]
            self.cur.execute(f"comment on column {table_name}_new.{column_name} is '{column_comment}';")

        # Insert rows by batch of INSERT_BATCH_SIZE.
        column_names = [f'{c["name"]}' for c in table_columns]
        statement = ", ".join(column_names)
        insert_query = f"insert into {table_name}_new ({statement}) values %s"
        with tqdm(total=len(objects)) as progress_bar:
            for chunk in chunks(objects, n=INSERT_BATCH_SIZE):
                data = [[c["lambda"](o) for c in table_columns] for o in chunk]
                psycopg2.extras.execute_values(self.cur, insert_query, data, template=None)
                progress_bar.update(len(chunk))

        # Swap new and old table nicely to minimize downtime.
        self.cur.execute(f"ALTER TABLE IF EXISTS {table_name} RENAME TO {table_name}_old;")
        self.cur.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name};")
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_old;")

    def populate_siaes(self):
        """
        Populate siaes table with various statistics.
        """
        table_name = "structures"

        objects = Siae.objects.prefetch_related("members", "siaemembership_set", "job_applications_received").all()[
            :MAX_ROWS_PER_TABLE
        ]

        table_columns = [
            {"name": "id", "type": "integer", "comment": "ID de la structure", "lambda": lambda o: o.id},
            {"name": "nom", "type": "varchar", "comment": "Nom de la structure", "lambda": lambda o: o.display_name},
            {
                "name": "description",
                "type": "varchar",
                "comment": "Description de la structure",
                "lambda": lambda o: o.description,
            },
            {
                "name": "type",
                "type": "varchar",
                "comment": "Type de structure (EI, ETTI, ACI, GEIQ etc..)",
                "lambda": lambda o: o.kind,
            },
            {"name": "siret", "type": "varchar", "comment": "SIRET de la structure", "lambda": lambda o: o.siret},
            {
                "name": "source",
                "type": "varchar",
                "comment": "Source des données de la structure",
                "lambda": lambda o: get_choice(choices=Siae.SOURCE_CHOICES, key=o.source),
            },
        ]

        table_columns += get_address_columns(comment_suffix=" de la structure")

        table_columns += [
            {
                "name": "date_inscription",
                "type": "date",
                "comment": "Date inscription du premier compte employeur",
                "lambda": get_siae_first_join_date,
            },
            {
                "name": "total_membres",
                "type": "integer",
                "comment": "Nombre de comptes employeur rattachés à la structure",
                "lambda": lambda o: o.members.count(),
            },
            {
                "name": "total_candidatures",
                "type": "integer",
                "comment": "Nombre de candidatures dont la structure est destinataire",
                "lambda": lambda o: len(o.job_applications_received.all()),
            },
            {
                "name": "total_auto_prescriptions",
                "type": "integer",
                "comment": "Nombre de candidatures de source employeur dont la structure est destinataire",
                # We have to do all this in python to benefit from prefetch_related.
                "lambda": lambda o: len(
                    [
                        ja
                        for ja in o.job_applications_received.all()
                        if ja.sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF
                    ]
                ),
            },
            {
                "name": "total_candidatures_autonomes",
                "type": "integer",
                "comment": "Nombre de candidatures de source candidat dont la structure est destinataire",
                # We have to do all this in python to benefit from prefetch_related.
                "lambda": lambda o: len(
                    [
                        ja
                        for ja in o.job_applications_received.all()
                        if ja.sender_kind == JobApplication.SENDER_KIND_JOB_SEEKER
                    ]
                ),
            },
            {
                "name": "total_candidatures_via_prescripteur",
                "type": "integer",
                "comment": "Nombre de candidatures de source prescripteur dont la structure est destinataire",
                # We have to do all this in python to benefit from prefetch_related.
                "lambda": lambda o: len(
                    [
                        ja
                        for ja in o.job_applications_received.all()
                        if ja.sender_kind == JobApplication.SENDER_KIND_PRESCRIBER
                    ]
                ),
            },
            {
                "name": "total_embauches",
                "type": "integer",
                "comment": "Nombre de candidatures en état accepté dont la structure est destinataire",
                # We have to do all this in python to benefit from prefetch_related.
                "lambda": lambda o: len(
                    [
                        ja
                        for ja in o.job_applications_received.all()
                        if ja.state == JobApplicationWorkflow.STATE_ACCEPTED
                    ]
                ),
            },
            {
                "name": "total_candidatures_non_traitées",
                "type": "integer",
                "comment": "Nombre de candidatures en état nouveau dont la structure est destinataire",
                # We have to do all this in python to benefit from prefetch_related.
                "lambda": lambda o: len(
                    [ja for ja in o.job_applications_received.all() if ja.state == JobApplicationWorkflow.STATE_NEW]
                ),
            },
            {
                "name": "total_candidatures_en_étude",
                "type": "integer",
                "comment": "Nombre de candidatures en état étude dont la structure est destinataire",
                # We have to do all this in python to benefit from prefetch_related.
                "lambda": lambda o: len(
                    [
                        ja
                        for ja in o.job_applications_received.all()
                        if ja.state == JobApplicationWorkflow.STATE_PROCESSING
                    ]
                ),
            },
            {"name": "longitude", "type": "float", "comment": "Longitude", "lambda": lambda o: o.longitude},
            {"name": "latitude", "type": "float", "comment": "Latitude", "lambda": lambda o: o.latitude},
        ]

        self.populate_table(table_name=table_name, table_columns=table_columns, objects=objects)

    def populate_organizations(self):
        """
        Populate prescriber organizations,
        and add a special "ORG_OF_PRESCRIBERS_WITHOUT_ORG" to gather stats
        of prescriber users *without* any organization.
        """
        table_name = "organisations"

        objects = [ORG_OF_PRESCRIBERS_WITHOUT_ORG] + list(
            PrescriberOrganization.objects.prefetch_related(
                "prescribermembership_set", "members", "jobapplication_set"
            ).all()[:MAX_ROWS_PER_TABLE]
        )

        table_columns = [
            {"name": "id", "type": "integer", "comment": "ID organisation", "lambda": lambda o: o.id},
            {"name": "nom", "type": "varchar", "comment": "Nom organisation", "lambda": lambda o: o.display_name},
            {
                "name": "type",
                "type": "varchar",
                "comment": "Type organisation (PE, ML...)",
                "lambda": lambda o: o.kind,
            },
            {
                "name": "habilitée",
                "type": "boolean",
                "comment": "Organisation habilitée par le préfet",
                "lambda": lambda o: o.is_authorized,
            },
        ]
        table_columns += get_address_columns(comment_suffix=" de cette organisation")
        table_columns += [
            {
                "name": "date_inscription",
                "type": "date",
                "comment": "Date inscription du premier compte prescripteur",
                "lambda": get_org_first_join_date,
            },
            {
                "name": "total_membres",
                "type": "integer",
                "comment": "Nombre de comptes prescripteurs rattachés à cette organisation",
                "lambda": get_org_members_count,
            },
            {
                "name": "total_candidatures",
                "type": "integer",
                "comment": "Nombre de candidatures émises par cette organisation",
                "lambda": get_org_job_applications_count,
            },
            {
                "name": "total_embauches",
                "type": "integer",
                "comment": "Nombre de candidatures en état accepté émises par cette organisation",
                "lambda": get_org_accepted_job_applications_count,
            },
            {
                "name": "temps_écoulé_depuis_dernière_candidature",
                "type": "interval",
                "comment": "Temps écoulé depuis la dernière création de candidature",
                "lambda": get_timedelta_since_org_last_job_application,
            },
        ]

        self.populate_table(table_name=table_name, table_columns=table_columns, objects=objects)

    def populate_job_applications(self):
        """
        Populate job applications table with various statistics.
        """
        table_name = "candidatures"

        objects = (
            JobApplication.objects.select_related("to_siae", "sender_siae", "sender_prescriber_organization")
            .prefetch_related("logs")
            .all()[:MAX_ROWS_PER_TABLE]
        )

        table_columns = [
            {
                "name": "id_anonymisé",
                "type": "varchar",
                "comment": "ID anonymisé de la candidature",
                "lambda": lambda o: anonymize(o.id, salt="job_application.id"),
            },
            {
                "name": "date_candidature",
                "type": "date",
                "comment": "Date de la candidature",
                "lambda": lambda o: o.created_at,
            },
            {
                "name": "état",
                "type": "varchar",
                "comment": "Etat de la candidature",
                "lambda": lambda o: get_choice(choices=JobApplicationWorkflow.STATE_CHOICES, key=o.state),
            },
            {
                "name": "type",
                "type": "varchar",
                "comment": (
                    "Type de la candidature (auto-prescription, candidature autonome, candidature via prescripteur)"
                ),
                "lambda": lambda o: get_choice(choices=SENDER_KIND_CHOICES, key=o.sender_kind),
            },
            {
                "name": "sous_type",
                "type": "varchar",
                "comment": (
                    "Sous-type de la candidature (auto-prescription par EI, ACI..."
                    " candidature autonome, candidature via prescripteur PE, ML...)"
                ),
                "lambda": get_job_application_sub_type,
            },
            {
                "name": "délai_prise_en_compte",
                "type": "interval",
                "comment": (
                    "Temps écoulé rétroactivement de état nouveau à état étude"
                    " si la candidature est passée par ces états"
                ),
                "lambda": get_ja_time_spent_from_new_to_processing,
            },
            {
                "name": "délai_de_réponse",
                "type": "interval",
                "comment": (
                    "Temps écoulé rétroactivement de état nouveau à état accepté"
                    " ou refusé si la candidature est passée par ces états"
                ),
                "lambda": get_ja_time_spent_from_new_to_accepted_or_refused,
            },
            {
                "name": "motif_de_refus",
                "type": "varchar",
                "comment": "Motif de refus de la candidature",
                "lambda": lambda o: get_choice(choices=JobApplication.REFUSAL_REASON_CHOICES, key=o.refusal_reason),
            },
            {
                "name": "id_candidat_anonymisé",
                "type": "varchar",
                "comment": "ID anonymisé du candidat",
                "lambda": lambda o: anonymize(o.job_seeker_id, salt="job_seeker.id"),
            },
            {
                "name": "id_structure",
                "type": "integer",
                "comment": "ID de la structure destinaire de la candidature",
                "lambda": lambda o: o.to_siae_id,
            },
            {
                "name": "type_structure",
                "type": "varchar",
                "comment": "Type de la structure destinaire de la candidature",
                "lambda": lambda o: o.to_siae.kind,
            },
            {
                "name": "nom_structure",
                "type": "varchar",
                "comment": "Nom de la structure destinaire de la candidature",
                "lambda": lambda o: o.to_siae.display_name,
            },
        ] + get_department_and_region_columns(
            name_suffix="_structure",
            comment_suffix=" de la structure destinaire de la candidature",
            custom_lambda=lambda o: o.to_siae,
        )

        self.populate_table(table_name=table_name, table_columns=table_columns, objects=objects)

    def populate_approvals(self):
        """
        Populate approvals table by merging Approvals and PoleEmploiApprovals.
        Some stats are available on both kinds of objects and some only
        on Approvals.
        We can link PoleEmploApproval back to its PrescriberOrganization via
        the SAFIR code.
        """
        table_name = "pass_agréments"

        objects = list(
            Approval.objects.prefetch_related(
                "user", "user__job_applications", "user__job_applications__to_siae"
            ).all()[: MAX_ROWS_PER_TABLE / 2]
        ) + list(
            PoleEmploiApproval.objects.filter(start_at__gte=POLE_EMPLOI_APPROVAL_MINIMUM_START_DATE).all()[
                : MAX_ROWS_PER_TABLE / 2
            ]
        )

        table_columns = [
            {"name": "type", "type": "varchar", "comment": "FIXME", "lambda": get_approval_type},
            {"name": "date_début", "type": "date", "comment": "Date de début", "lambda": lambda o: o.start_at},
            {"name": "date_fin", "type": "date", "comment": "Date de fin", "lambda": lambda o: o.end_at},
            {"name": "durée", "type": "interval", "comment": "Durée", "lambda": lambda o: o.end_at - o.start_at},
            # -------- Field not ready for code review yet --------
            # # The rigorous date would be:
            # # $ job_application.approval_number_sent_at
            # # however some approvals have two or more job_applications
            # # with different approval_number_sent_at values.
            # # Thus we simply use approval.created_at here.
            # {
            #     "name": "date_de_délivrance",
            #     "type": "date",
            #     "comment": "Date de délivrance si Pass IAE",
            #     "lambda": lambda o: o.created_at if isinstance(o, Approval) else None,
            # },
            # ------------------------------------------------------
            {
                "name": "id_structure",
                "type": "integer",
                "comment": "ID structure qui a embauché si Pass IAE",
                "lambda": lambda o: get_siae_from_approval(o).id if get_siae_from_approval(o) else None,
            },
            {
                "name": "type_structure",
                "type": "varchar",
                "comment": "Type de la structure qui a embauché si Pass IAE",
                "lambda": lambda o: get_siae_from_approval(o).kind if get_siae_from_approval(o) else None,
            },
            {
                "name": "siret_structure",
                "type": "varchar",
                "comment": "SIRET de la structure qui a embauché si Pass IAE",
                "lambda": lambda o: get_siae_from_approval(o).siret if get_siae_from_approval(o) else None,
            },
            {
                "name": "nom_structure",
                "type": "varchar",
                "comment": "Nom de la structure qui a embauché si Pass IAE",
                "lambda": lambda o: get_siae_from_approval(o).display_name if get_siae_from_approval(o) else None,
            },
        ] + get_department_and_region_columns(
            name_suffix="_structure_ou_org_pe",
            comment_suffix=(
                " de la structure qui a embauché si Pass IAE ou" " du PE qui a délivré l agrément si Agrément PE"
            ),
            custom_lambda=get_siae_or_pe_org_from_approval,
        )

        self.populate_table(table_name=table_name, table_columns=table_columns, objects=objects)

    def populate_job_seekers(self):
        """
        Populate job seekers table and add detailed stats about
        diagnoses and administrative criteria, including one column
        for each of the 15 possible criteria.

        Note that job seeker id is anonymized.
        """
        table_name = "candidats"

        objects = (
            get_user_model()
            .objects.filter(is_job_seeker=True)
            .prefetch_related(
                "job_applications",
                "eligibility_diagnoses",
                "eligibility_diagnoses__administrative_criteria",
                "socialaccount_set",
                "eligibility_diagnoses__author_prescriber_organization",
                "eligibility_diagnoses__author_siae",
            )
            .all()[:MAX_ROWS_PER_TABLE]
        )

        table_columns = [
            {
                "name": "id_anonymisé",
                "type": "varchar",
                "comment": "ID anonymisé du candidat",
                "lambda": lambda o: anonymize(o.id, salt="job_seeker.id"),
            },
            {
                "name": "age",
                "type": "integer",
                "comment": "Age du candidat en années",
                "lambda": get_user_age_in_years,
            },
            {
                "name": "date_inscription",
                "type": "date",
                "comment": "Date inscription du candidat",
                "lambda": lambda o: o.date_joined,
            },
            {
                "name": "pe_connect",
                "type": "boolean",
                "comment": "Le candidat utilise PE Connect",
                "lambda": lambda o: o.is_peamu,
            },
            {
                "name": "dernière_connexion",
                "type": "date",
                "comment": "Date de dernière connexion au service du candidat",
                "lambda": lambda o: o.last_login,
            },
            {
                "name": "actif",
                "type": "boolean",
                "comment": "Dernière connexion dans les 7 jours",
                "lambda": lambda o: o.last_login > datetime.now(timezone.utc) + timedelta(days=-7)
                if o.last_login
                else None,
            },
        ]
        table_columns += get_department_and_region_columns(comment_suffix=" du candidat")
        table_columns += [
            {
                "name": "total_candidatures",
                "type": "integer",
                "comment": "Nombre de candidatures",
                "lambda": lambda o: o.job_applications.count(),
            },
            {
                "name": "total_embauches",
                "type": "integer",
                "comment": "Nombre de candidatures de type accepté",
                # We have to do all this in python to benefit from prefetch_related.
                "lambda": lambda o: len(
                    [ja for ja in o.job_applications.all() if ja.state == JobApplicationWorkflow.STATE_ACCEPTED]
                ),
            },
            {
                "name": "total_diagnostics",
                "type": "integer",
                "comment": "Nombre de diagnostics",
                "lambda": lambda o: o.eligibility_diagnoses.count(),
            },
            {
                "name": "date_diagnostic",
                "type": "date",
                "comment": "Date du dernier diagnostic",
                "lambda": lambda o: get_latest_diagnosis(o).created_at if get_latest_diagnosis(o) else None,
            },
            {
                "name": "type_auteur_diagnostic",
                "type": "varchar",
                "comment": "Type auteur du dernier diagnostic",
                "lambda": lambda o: get_choice(choices=AUTHOR_KIND_CHOICES, key=get_latest_diagnosis(o).author_kind)
                if get_latest_diagnosis(o)
                else None,
            },
            {
                "name": "sous_type_auteur_diagnostic",
                "type": "varchar",
                "comment": "Sous type auteur du dernier diagnostic",
                "lambda": get_latest_diagnosis_author_sub_kind,
            },
            {
                "name": "type_structure_dernière_embauche",
                "type": "varchar",
                "comment": "Type de la structure destinataire de la dernière embauche du candidat",
                "lambda": lambda o: JOB_SEEKER_ID_TO_HIRING_SIAE[o.id].kind
                if JOB_SEEKER_ID_TO_HIRING_SIAE.get(o.id)
                else None,
            },
            {
                "name": "total_critères_niveau_1",
                "type": "integer",
                "comment": "Total critères de niveau 1 du dernier diagnostic",
                "lambda": get_latest_diagnosis_level1_criteria,
            },
            {
                "name": "total_critères_niveau_2",
                "type": "integer",
                "comment": "Total critères de niveau 2 du dernier diagnostic",
                "lambda": get_latest_diagnosis_level2_criteria,
            },
        ]

        # Add one column for each of the 15 criteria.
        for criteria in AdministrativeCriteria.objects.order_by("id").all():
            # Make criteria name prettier to read.
            column_comment = (
                criteria.name.replace("'", " ")
                .replace("12-24", "12 à 24")
                .replace("+", "plus de ")
                .replace("-", "moins de ")
                .strip()
            )

            # Deduplicate consecutive spaces.
            column_comment = " ".join(column_comment.split())
            column_name = column_comment.replace("(", "").replace(")", "").replace(" ", "_").lower()

            table_columns += [
                {
                    "name": f"critère_n{criteria.level}_{column_name}",
                    "type": "boolean",
                    "comment": f"Critère {column_comment} (niveau {criteria.level})",
                    "lambda": partial(get_latest_diagnosis_criteria, criteria_id=criteria.id),
                }
            ]

        self.populate_table(table_name=table_name, table_columns=table_columns, objects=objects)

    def populate_metabase(self):
        with MetabaseDatabaseCursor() as cur:
            self.cur = cur
            self.populate_siaes()
            self.populate_organizations()
            self.populate_job_seekers()
            self.populate_job_applications()
            self.populate_approvals()

    def handle(self, **options):
        self.set_logger(options.get("verbosity"))
        self.populate_metabase()
        self.log("-" * 80)
        self.log("Done.")
