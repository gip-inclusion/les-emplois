from datetime import date, timedelta
from functools import partial

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.job_applications.models import JobApplicationWorkflow
from itou.metabase.management.commands._utils import (
    JOB_SEEKER_ID_TO_HIRING_SIAE,
    anonymize,
    get_choice,
    get_department_and_region_columns,
)


# Reword the original EligibilityDiagnosis.AUTHOR_KIND_CHOICES
AUTHOR_KIND_CHOICES = (
    (EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER, _("Prescripteur")),
    (EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF, _("Employeur")),
)


def get_user_age_in_years(user):
    if user.birthdate:
        return date.today().year - user.birthdate.year
    return None


def _get_job_seeker_id_to_latest_diagnosis():
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


JOB_SEEKER_ID_TO_LATEST_DIAGNOSIS = _get_job_seeker_id_to_latest_diagnosis()


## WIP
import sys


def get_size(obj, seen=None):
    """Recursively finds size of objects"""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    # Important mark as seen *before* entering recursion to gracefully handle
    # self-referential objects
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, "__dict__"):
        size += get_size(obj.__dict__, seen)
    elif hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, bytearray)):
        size += sum([get_size(i, seen) for i in obj])
    return size


# get_size(JOB_SEEKER_ID_TO_LATEST_DIAGNOSIS)
# 262053173 - 260MB

# WIP


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
        author_sub_kind = None
        if (
            latest_diagnosis.author_kind == EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF
            and latest_diagnosis.author_siae
        ):
            author_sub_kind = latest_diagnosis.author_siae.kind
        elif (
            latest_diagnosis.author_kind == EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER
            and latest_diagnosis.author_prescriber_organization
        ):
            author_sub_kind = latest_diagnosis.author_prescriber_organization.kind
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


TABLE_COLUMNS = (
    [
        {
            "name": "id_anonymisé",
            "type": "varchar",
            "comment": "ID anonymisé du candidat",
            "lambda": lambda o: anonymize(o.id, salt="job_seeker.id"),
        },
        {"name": "age", "type": "integer", "comment": "Age du candidat en années", "lambda": get_user_age_in_years},
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
            "name": "date_dernière_connexion",
            "type": "date",
            "comment": "Date de dernière connexion au service du candidat",
            "lambda": lambda o: o.last_login,
        },
        {
            "name": "actif",
            "type": "boolean",
            "comment": "Dernière connexion dans les 7 jours",
            "lambda": lambda o: o.last_login > timezone.now() + timedelta(days=-7) if o.last_login else None,
        },
    ]
    + get_department_and_region_columns(comment_suffix=" du candidat")
    + [
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
            "lambda": lambda o: getattr(get_latest_diagnosis(o), "created_at", None),
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
)

# Add one column for each of the 15 criteria.
for criteria in AdministrativeCriteria.objects.order_by("id").all():
    # Make criteria name prettier to read.
    column_comment = (
        criteria.name.replace("'", " ")
        .replace(",", "")
        .replace("12-24", "12 à 24")
        .replace("+", "plus de ")
        .replace("-", "moins de ")
        .strip()
    )

    # Deduplicate consecutive spaces.
    column_comment = " ".join(column_comment.split())
    column_name = column_comment.replace("(", "").replace(")", "").replace(" ", "_").lower()

    TABLE_COLUMNS += [
        {
            "name": f"critère_n{criteria.level}_{column_name}",
            "type": "boolean",
            "comment": f"Critère {column_comment} (niveau {criteria.level})",
            "lambda": partial(get_latest_diagnosis_criteria, criteria_id=criteria.id),
        }
    ]
