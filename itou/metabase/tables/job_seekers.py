from datetime import date, timedelta
from functools import partial

from django.utils import timezone

from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE
from itou.eligibility.enums import AdministrativeCriteriaLevel, AuthorKind
from itou.eligibility.models import AdministrativeCriteria
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_ai_stock_job_seeker_pks,
    get_choice,
    get_department_and_region_columns,
    get_hiring_company,
    get_post_code_column,
    get_qpv_job_seeker_pks,
    hash_content,
)
from itou.users.enums import IdentityProvider


# Reword the original EligibilityDiagnosis.AUTHOR_KIND_CHOICES
AUTHOR_KIND_CHOICES = (
    (AuthorKind.PRESCRIBER, "Prescripteur"),
    (AuthorKind.EMPLOYER, "Employeur"),
)


def get_user_age_in_years(user):
    if user.birthdate:
        return date.today().year - user.birthdate.year
    return None


def get_user_signup_kind(user):
    creator = user.created_by
    if creator is None:
        return "autonome"
    if creator.is_prescriber:
        return "par prescripteur"
    if creator.is_employer:
        return "par employeur"
    if creator.is_staff:
        return "par administrateur"
    raise ValueError("Unexpected job seeker creator kind")


def get_latest_diagnosis(job_seeker):
    assert job_seeker.is_job_seeker
    if job_seeker.eligibility_diagnoses_count == 0:
        return None
    return job_seeker.last_eligibility_diagnosis[0]


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
        if latest_diagnosis.author_kind == AuthorKind.EMPLOYER and latest_diagnosis.author_siae:
            author_sub_kind = latest_diagnosis.author_siae.kind
        elif latest_diagnosis.author_kind == AuthorKind.PRESCRIBER and latest_diagnosis.author_prescriber_organization:
            author_sub_kind = latest_diagnosis.author_prescriber_organization.kind
        return f"{author_kind} {author_sub_kind}"
    return None


def get_latest_diagnosis_author_display_name(job_seeker):
    latest_diagnosis = get_latest_diagnosis(job_seeker)
    if latest_diagnosis:
        if latest_diagnosis.author_kind == AuthorKind.EMPLOYER and latest_diagnosis.author_siae:
            return latest_diagnosis.author_siae.display_name
        elif latest_diagnosis.author_kind == AuthorKind.PRESCRIBER and latest_diagnosis.author_prescriber_organization:
            return latest_diagnosis.author_prescriber_organization.display_name
    return None


def _get_latest_diagnosis_criteria_by_level(job_seeker, level):
    """
    Count criteria of given level for the latest diagnosis of
    given job seeker.
    """
    latest_diagnosis = get_latest_diagnosis(job_seeker)
    if latest_diagnosis:
        if level == AdministrativeCriteriaLevel.LEVEL_1:
            return latest_diagnosis.level_1_count
        if level == AdministrativeCriteriaLevel.LEVEL_2:
            return latest_diagnosis.level_2_count
    return None


def get_latest_diagnosis_level1_criteria(job_seeker):
    return _get_latest_diagnosis_criteria_by_level(job_seeker=job_seeker, level=AdministrativeCriteriaLevel.LEVEL_1)


def get_latest_diagnosis_level2_criteria(job_seeker):
    return _get_latest_diagnosis_criteria_by_level(job_seeker=job_seeker, level=AdministrativeCriteriaLevel.LEVEL_2)


def get_latest_diagnosis_criteria(job_seeker, criteria_id):
    """
    Check if given criteria_id is actually present in latest diagnosis
    of given job seeker.

    Return 1 if present, 0 if absent and None if there is no diagnosis.
    """
    latest_diagnosis = get_latest_diagnosis(job_seeker)
    if latest_diagnosis:
        return criteria_id in latest_diagnosis.criteria_ids
    return None


def _format_criteria_name_as_column_comment(criteria):
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
    return column_comment


def format_criteria_name_as_column_name(criteria):
    column_comment = _format_criteria_name_as_column_comment(criteria)
    column_name = column_comment.replace("(", "").replace(")", "").replace(" ", "_").lower()
    return f"critère_n{criteria.level}_{column_name}"


def get_gender_from_nir(job_seeker):
    if job_seeker.jobseeker_profile.nir:
        match job_seeker.jobseeker_profile.nir[0]:
            case "1":
                return "Homme"
            case "2":
                return "Femme"
            case _:
                raise ValueError("Unexpected NIR first digit")
    return None


def get_birth_year_from_nir(job_seeker):
    if nir := job_seeker.jobseeker_profile.nir:
        # It will be our data analysts' job to decide whether `05` means `1905` or `2005`.
        birth_year = int(nir[1:3])
        return birth_year
    return None


def get_birth_month_from_nir(job_seeker):
    if nir := job_seeker.jobseeker_profile.nir:
        birth_month = int(nir[3:5])
        if not 1 <= birth_month <= 12:
            # Exotic values means the birth month is unknown, as the 31-42 range was never observed in our data.
            # https://fr.wikipedia.org/wiki/Num%C3%A9ro_de_s%C3%A9curit%C3%A9_sociale_en_France#ancrage_B
            birth_month = 0
        return birth_month
    return None


def get_job_seeker_qpv_info(job_seeker):
    if not job_seeker.coords:
        return "Adresse non-géolocalisée"
    elif job_seeker.geocoding_score is not None and job_seeker.geocoding_score < BAN_API_RELIANCE_SCORE:
        return "Adresse imprécise"
    if job_seeker.pk in get_qpv_job_seeker_pks():
        return "Adresse en QPV"
    return "Adresse hors QPV"


def get_table():
    job_seekers_table = MetabaseTable(name="candidats_v0")

    job_seekers_table.add_columns(
        [
            {
                "name": "id",
                "type": "integer",
                "comment": "ID C1 du candidat",
                "fn": lambda o: o.pk,
            },
            {
                "name": "hash_nir",
                "type": "varchar",
                "comment": "Version obfusquée du NIR",
                "fn": lambda o: hash_content(o.jobseeker_profile.nir) if o.jobseeker_profile.nir else None,
            },
            {
                "name": "sexe_selon_nir",
                "type": "varchar",
                "comment": "Sexe du candidat selon le NIR",
                "fn": get_gender_from_nir,
            },
            {
                "name": "annee_naissance_selon_nir",
                "type": "integer",
                "comment": "Année de naissance du candidat selon le NIR",
                "fn": get_birth_year_from_nir,
            },
            {
                "name": "mois_naissance_selon_nir",
                "type": "integer",
                "comment": "Mois de naissance du candidat selon le NIR",
                "fn": get_birth_month_from_nir,
            },
            {"name": "age", "type": "integer", "comment": "Age du candidat en années", "fn": get_user_age_in_years},
            {
                "name": "date_inscription",
                "type": "date",
                "comment": "Date inscription du candidat",
                "fn": lambda o: o.date_joined,
            },
            {
                "name": "type_inscription",
                "type": "varchar",
                "comment": "Type inscription du candidat",
                "fn": get_user_signup_kind,
            },
            {
                "name": "pe_connect",
                "type": "boolean",
                "comment": "Le candidat utilise PE Connect",
                "fn": lambda o: o.identity_provider == IdentityProvider.PE_CONNECT,
            },
            {
                "name": "pe_inscrit",
                "type": "boolean",
                "comment": "Le candidat a un identifiant PE",
                "fn": lambda o: o.jobseeker_profile.pole_emploi_id != "",
            },
            {
                "name": "date_dernière_connexion",
                "type": "date",
                "comment": "Date de dernière connexion au service du candidat",
                "fn": lambda o: o.last_login,
            },
            {
                "name": "actif",
                "type": "boolean",
                "comment": "Dernière connexion dans les 7 jours",
                "fn": lambda o: o.last_login > timezone.now() + timedelta(days=-7) if o.last_login else False,
            },
        ]
    )

    job_seekers_table.add_columns([get_post_code_column(comment_suffix=" du candidat")])

    job_seekers_table.add_columns(get_department_and_region_columns(comment_suffix=" du candidat"))

    job_seekers_table.add_columns(
        [
            {
                "name": "adresse_en_qpv",
                "type": "varchar",
                "comment": "Analyse QPV sur adresse du candidat",
                "fn": get_job_seeker_qpv_info,
            },
            {
                "name": "total_candidatures",
                "type": "integer",
                "comment": "Nombre de candidatures",
                "fn": lambda o: o.job_applications_count,
            },
            {
                "name": "total_embauches",
                "type": "integer",
                "comment": "Nombre de candidatures de type accepté",
                # We have to do all this in python to benefit from prefetch_related.
                "fn": lambda o: o.accepted_job_applications_count,
            },
            {
                "name": "total_diagnostics",
                "type": "integer",
                "comment": "Nombre de diagnostics",
                "fn": lambda o: o.eligibility_diagnoses_count,
            },
            {
                "name": "date_diagnostic",
                "type": "date",
                "comment": "Date du dernier diagnostic",
                "fn": lambda o: getattr(get_latest_diagnosis(o), "created_at", None),
            },
            {
                "name": "id_auteur_diagnostic_prescripteur",
                "type": "integer",
                "comment": "ID auteur diagnostic si prescripteur",
                "fn": lambda o: (
                    get_latest_diagnosis(o).author_prescriber_organization.id
                    if get_latest_diagnosis(o)
                    and get_latest_diagnosis(o).author_kind == AuthorKind.PRESCRIBER
                    and get_latest_diagnosis(o).author_prescriber_organization
                    else None
                ),
            },
            {
                "name": "id_auteur_diagnostic_employeur",
                "type": "integer",
                "comment": "ID auteur diagnostic si employeur",
                "fn": lambda o: (
                    get_latest_diagnosis(o).author_siae.id
                    if get_latest_diagnosis(o)
                    and get_latest_diagnosis(o).author_kind == AuthorKind.EMPLOYER
                    and get_latest_diagnosis(o).author_siae
                    else None
                ),
            },
            {
                "name": "type_auteur_diagnostic",
                "type": "varchar",
                "comment": "Type auteur du dernier diagnostic",
                "fn": lambda o: (
                    get_choice(choices=AUTHOR_KIND_CHOICES, key=get_latest_diagnosis(o).author_kind)
                    if get_latest_diagnosis(o)
                    else None
                ),
            },
            {
                "name": "sous_type_auteur_diagnostic",
                "type": "varchar",
                "comment": "Sous type auteur du dernier diagnostic",
                "fn": get_latest_diagnosis_author_sub_kind,
            },
            {
                "name": "nom_auteur_diagnostic",
                "type": "varchar",
                "comment": "Nom auteur du dernier diagnostic",
                "fn": get_latest_diagnosis_author_display_name,
            },
            {
                "name": "type_structure_dernière_embauche",
                "type": "varchar",
                "comment": "Type de la structure destinataire de la dernière embauche du candidat",
                "fn": lambda o: get_hiring_company(o).kind if get_hiring_company(o) else None,
            },
            {
                "name": "total_critères_niveau_1",
                "type": "integer",
                "comment": "Total critères de niveau 1 du dernier diagnostic",
                "fn": get_latest_diagnosis_level1_criteria,
            },
            {
                "name": "total_critères_niveau_2",
                "type": "integer",
                "comment": "Total critères de niveau 2 du dernier diagnostic",
                "fn": get_latest_diagnosis_level2_criteria,
            },
        ]
    )

    # Add one column for each of the 15 criteria.
    for criteria in AdministrativeCriteria.objects.order_by("id").all():
        column_comment = _format_criteria_name_as_column_comment(criteria)
        column_name = format_criteria_name_as_column_name(criteria)

        job_seekers_table.add_columns(
            [
                {
                    "name": column_name,
                    "type": "boolean",
                    "comment": f"Critère {column_comment} (niveau {criteria.level})",
                    "fn": partial(get_latest_diagnosis_criteria, criteria_id=criteria.id),
                }
            ]
        )

    job_seekers_table.add_columns(
        [
            {
                "name": "injection_ai",
                "type": "boolean",
                "comment": "Provient des injections AI",
                # Here we flag job seekers as soon as any of their approvals is from the AI stock.
                # In theory we should only flag them when their latest approval `o.approvals_wrapper.latest_approval`
                # matches, but the performance becomes terrible (e.g. 120 minutes vs 30 minutes), is not easy to fix
                # due to how `approvals_wrapper.latest_approval` is implemented and gives the exact same end result
                # anyway (71205 users), most likely since most if not all of these users only have a single approval
                # anyway.
                # FIXME(vperron): It would be interesting to test again now though.
                "fn": lambda o: o.pk in get_ai_stock_job_seeker_pks(),
            },
        ]
    )

    return job_seekers_table
