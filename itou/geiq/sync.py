import datetime
import logging

from django.conf import settings
from django.utils import timezone

from itou.companies.models import Company, CompanyKind
from itou.eligibility.enums import AdministrativeCriteriaAnnex, AdministrativeCriteriaLevel
from itou.eligibility.models import GEIQAdministrativeCriteria
from itou.eligibility.utils import geiq_allowance_amount
from itou.users.enums import Title
from itou.utils.apis import geiq_label
from itou.utils.sync import DiffItemKind, yield_sync_diff

from . import models


logger = logging.getLogger(__name__)


def convert_iso_datetime_to_date(iso_datetime):
    # We receive '1970-01-01T00:00:00+0100' or '2022-09-19T00:00:00+0200' values for dates
    return datetime.date.fromisoformat(iso_datetime[:10])


def label_data_to_django(data, *, mapping, model):
    model_data = {}
    other_data = dict(data)
    for db_key, label_key in mapping.items():
        model_data[db_key] = data[label_key]
        other_data.pop(label_key)
    model_data["other_data"] = other_data
    return model(**model_data)


GEIQ_MAPPING = {
    "label_id": "id",
}


def sync_to_db(api_data, db_queryset, *, model, mapping, data_to_django_obj, with_delete=False):
    obj_to_create = []
    obj_to_update = []
    obj_to_delete = []

    def get_other_data(label_data):
        # Compute other_data field
        return {k: v for k, v in label_data.items() if k not in mapping.values()}

    for item in yield_sync_diff(
        api_data,
        "id",
        db_queryset,
        "label_id",
        [(label_key, db_key) for db_key, label_key in mapping.items()] + [(get_other_data, "other_data")],
    ):
        if item.kind in [DiffItemKind.ADDITION, DiffItemKind.EDITION]:
            obj = data_to_django_obj(item.raw, mapping=mapping, model=model)
            if item.kind == DiffItemKind.ADDITION:
                obj_to_create.append(obj)
            else:
                obj.pk = item.db_obj.pk
                obj_to_update.append(obj)
        elif item.kind == DiffItemKind.DELETION:
            obj_to_delete.append(item.key)

    logger.info("Label sync will create nb=%d type=%s", len(obj_to_create), model._meta.verbose_name)
    logger.info("Label sync will update nb=%d type=%s", len(obj_to_update), model._meta.verbose_name)
    delete_prefix = "will delete" if with_delete else "would delete"
    logger.info(f"Label sync {delete_prefix} nb=%d type=%s", len(obj_to_delete), model._meta.verbose_name)
    model.objects.bulk_create(obj_to_create)
    model.objects.bulk_update(obj_to_update, {"other_data"} | {db_key for db_key in mapping if db_key != "label_id"})
    if with_delete:
        model.objects.filter(label_id__in=obj_to_delete).delete()
    return obj_to_create, obj_to_update, obj_to_delete


def sync_assessments(campaign):
    siret_to_company = {
        company.siret: company for company in Company.objects.filter(kind=CompanyKind.GEIQ).exclude(siret="")
    }
    client = geiq_label.get_client()
    geiq_infos = client.get_all_geiq()

    geiq_label_infos = []
    for geiq_info in geiq_infos:
        if not geiq_info["siret"]:
            logger.info("Ignoring geiq=%r without SIRET", geiq_info["nom"])
            continue
        if geiq_info["siret"] not in siret_to_company:
            logger.info("Ignoring geiq=%r with unknown SIRET=%s", geiq_info["nom"], geiq_info["siret"])
            continue
        if geiq_info["id"] == 27 and geiq_info["nom"] == "GEIQ ACCUEIL MIDI-PYRENEES":
            # Duplicate of 45053310400045
            logger.info("Ignoring geiq=%r with duplicate SIRET of geiq 107", geiq_info["nom"])
            continue
        if geiq_info["id"] == 133 and geiq_info["nom"] == "GEIQ METIERS DU TOURISME PAYS DE SAVOIE":
            # Duplicate of 80784132500010
            logger.info("Ignoring geiq=%r with duplicate SIRET of geiq 216", geiq_info["nom"])
            continue
        if geiq_info["id"] == 190 and geiq_info["nom"] == "JOUBERT":
            # Duplicate of 44041441500040
            logger.info("Ignoring geiq=%r with duplicate SIRET of geiq 151", geiq_info["nom"])
            continue
        if geiq_info["id"] == 191 and geiq_info["nom"] == "POURRET ":
            # Duplicate of 75121328100015
            logger.info("Ignoring geiq=%r with duplicate SIRET of geiq 112", geiq_info["nom"])
            continue
        if (allowed_postcode_prefixes := settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES) and not geiq_info[
            "cp"
        ].startswith(tuple(allowed_postcode_prefixes)):
            logger.info("Ignoring geiq=%r since its cp=%s is not allowed", geiq_info["nom"], geiq_info["cp"])
            continue
        geiq_label_infos.append(geiq_info)

    def geiq_data_to_django(data, *, mapping, model):
        assessment = label_data_to_django(data, mapping=mapping, model=model)
        assessment.company = siret_to_company[data["siret"]]
        assessment.campaign = campaign
        return assessment

    return sync_to_db(
        geiq_label_infos,
        models.ImplementationAssessment.objects.filter(campaign=campaign),
        model=models.ImplementationAssessment,
        mapping=GEIQ_MAPPING,
        data_to_django_obj=geiq_data_to_django,
    )


EMPLOYEE_MAPPING = {
    "label_id": "id",
    "last_name": "nom",
    "first_name": "prenom",
    "title": "sexe",
    "birthdate": "date_naissance",
    # Those are computed locally
    # based on statuts_prioritaire field & GEIQAdministrativeCriteria objects
    "annex1_nb": "annex1_nb",
    "annex2_level1_nb": "annex2_level1_nb",
    "annex2_level2_nb": "annex2_level2_nb",
    "allowance_amount": "allowance_amount",
    # based on contracts & prequalification periods
    "support_days_nb": "support_days_nb",
}


CONTRACT_MAPPING = {
    "label_id": "id",
    "start_at": "date_debut",
    "planned_end_at": "date_fin",
    "end_at": "date_fin_contrat",
}


PREQUALIFICATION_MAPPING = {
    "label_id": "id",
    "start_at": "date_debut",
    "end_at": "date_fin",
}


def _cleanup_employee_info(employee_info):
    employee_info["date_naissance"] = convert_iso_datetime_to_date(employee_info["date_naissance"])
    employee_info["sexe"] = {"H": Title.M, "F": Title.MME}[employee_info["sexe"]]


def _compute_eligibility_fields(api_codes, code_to_criteria, support_days_nb):
    authorized_prescriber = False
    emplois_codes = set()
    # Handle Demandeur d'asile / Réfugiés statutaire ou bénéficiaire de la protection subsidiaire special case
    REFUG = "Refug."
    RS_PS_DA = "RS/PS/DA"
    if REFUG in api_codes:
        # Refug. code should imply the presence of RS/PS/DA code
        # Add our Annex 1+2 criteria "Réfugiés statutaire ou bénéficiaire de la protection subsidiaire"
        emplois_codes.add(f"{REFUG}|{RS_PS_DA}")
        # Remove REFUG & RS/PS/DA to avoid also adding Annex 1 criteria "Demandeur d'asile" with the RS/PS/DA api_code
        api_codes = {code for code in api_codes if code not in (REFUG, RS_PS_DA)}

    if "QPV/ZRR" in api_codes:
        if not {"QPV", "ZRR"} & api_codes:
            # Label has the QPV/ZRR Annex 1 criteria but none of the QPV & ZRR annex 2 criteria
            # since both are at the same level: we arbitrarly choose QPV for our computation
            api_codes |= {"QPV"}
        api_codes -= {"QPV/ZRR"}

    # Add all the known criteria
    emplois_codes |= api_codes & set(code_to_criteria)

    for unknown_code in api_codes - set(code_to_criteria):
        match unknown_code:
            # Codes to ignore
            case "Aucun":
                pass
            case "Reconv.Vol":
                # It states it is an "Expérimentation. Hors critères": ignore it
                pass
            case "Prescrit":
                # Prescrit means "Est prescrit via la Plateforme de l’inclusion par un prescripteur habilité" in Label
                # but we should really use the prescripteur field
                authorized_prescriber = True
            # Travailleur handicapé
            case "Pers. SH" | "TH":
                emplois_codes.add("Pers. SH|TH")
            # Sortant de détention ou personne placée sous main de justice
            case "Detention/MJ" | "Prison":
                emplois_codes.add("Detention/MJ|Prison")
            # QPV & ZRR
            case "QPV":
                emplois_codes.add("QPV|QPV/ZRR")
            case "ZRR":
                emplois_codes.add("ZRR|QPV/ZRR")
            case _:
                raise ValueError(f"Unknown code: {unknown_code}")

    annex1_nb = annex2_level1_nb = annex2_level2_nb = 0
    administrative_criterias = [code_to_criteria[code] for code in emplois_codes]
    for criteria in administrative_criterias:
        if criteria.annex in (AdministrativeCriteriaAnnex.ANNEX_1, AdministrativeCriteriaAnnex.BOTH_ANNEXES):
            annex1_nb += 1
        if criteria.annex in (AdministrativeCriteriaAnnex.ANNEX_2, AdministrativeCriteriaAnnex.BOTH_ANNEXES):
            match criteria.level:
                case AdministrativeCriteriaLevel.LEVEL_1:
                    annex2_level1_nb += 1
                case AdministrativeCriteriaLevel.LEVEL_2:
                    annex2_level2_nb += 1
    if support_days_nb < 90:
        allowance_amount = 0
    else:
        allowance_amount = geiq_allowance_amount(
            is_authorized_prescriber=authorized_prescriber, administrative_criteria=administrative_criterias
        )

    return {
        "annex1_nb": annex1_nb,
        "annex2_level1_nb": annex2_level1_nb,
        "annex2_level2_nb": annex2_level2_nb,
        "allowance_amount": allowance_amount,
    }


def _nb_days(periods: list[tuple[datetime.date, datetime.date]], *, year: int):
    YEAR_START = datetime.date(year, 1, 1)
    YEAR_END = datetime.date(year, 12, 31)
    nb_days = 0
    cleaned_periods = []
    # Sort & truncate periods to target year
    for start, end in sorted(periods):
        if start > end:
            # Ignore invalid period
            continue
        if end < YEAR_START or start > YEAR_END:
            # Period outside of year
            continue
        new_end = min(end, YEAR_END)
        new_start = max(start, YEAR_START)
        cleaned_periods.append((new_start, new_end))
    if not cleaned_periods:
        return nb_days

    current_start, current_end = cleaned_periods.pop(0)
    while cleaned_periods:
        new_start, new_end = cleaned_periods.pop(0)
        if new_start <= current_end:  # overlapping periods
            if new_end <= current_end:
                # Drop the new period that is totally included in current one
                continue
            # else new_end > current_end
            current_end = new_end
        else:  # new_start > current_end
            # new distinct period found: count the current one and switch to the new one
            nb_days += (current_end - current_start).days + 1
            current_start, current_end = new_start, new_end
    # All periods have been either counted or collapsed
    nb_days += (current_end - current_start).days + 1
    return nb_days


def sync_employee_and_contracts(assessment):
    assert not assessment.submitted_at
    client = geiq_label.get_client()
    geiq_id = assessment.label_id

    contract_infos = []
    prequalification_infos = []
    employee_infos = {}
    employee_support_periods = {}
    for contract_info in client.get_all_contracts(geiq_id):
        contract_info["date_debut"] = convert_iso_datetime_to_date(contract_info["date_debut"])
        contract_info["date_fin"] = convert_iso_datetime_to_date(contract_info["date_fin"])
        contract_info["date_fin_contrat"] = (
            convert_iso_datetime_to_date(contract_info["date_fin_contrat"])
            if contract_info["date_fin_contrat"]
            else None
        )
        if contract_info["date_debut"].year > assessment.campaign.year:
            # Ignoring contract starting after assessment year
            continue
        # Use the real enddate or the planned one
        # If a contract was planned to end in 2023 but ended in 2022,
        # its data is irrelevant for 2023 assessment: ignore it
        end_date = contract_info["date_fin_contrat"] or contract_info["date_fin"]
        if end_date.year < assessment.campaign.year:
            # Ignoring contract ending before assessment year
            continue

        employee_info = contract_info["salarie"]
        _cleanup_employee_info(employee_info)
        if employee_info["id"] in employee_infos:
            # Check consistency between contracts
            assert (
                employee_infos[employee_info["id"]] == employee_info
            ), f"{employee_info} != {employee_infos[employee_info['id']]}"
        else:
            employee_infos[employee_info["id"]] = employee_info
        contract_info["salarie"] = employee_info["id"]
        contract_infos.append(contract_info)
        employee_support_periods.setdefault(employee_info["id"], []).append((contract_info["date_debut"], end_date))

    for prequalification_info in client.get_all_prequalifications(geiq_id):
        employee_info = prequalification_info["salarie"]
        _cleanup_employee_info(employee_info)
        if employee_info["id"] in employee_infos:
            # Check consistency between contracts & prequalifications
            assert (
                employee_infos[employee_info["id"]] == employee_info
            ), f"{employee_info} != {employee_infos[employee_info['id']]}"
        else:
            # Ignore prequalifications for employees without active contract in assessment year
            continue
        prequalification_info["salarie"] = employee_info["id"]
        prequalification_info["date_debut"] = convert_iso_datetime_to_date(prequalification_info["date_debut"])
        prequalification_info["date_fin"] = convert_iso_datetime_to_date(prequalification_info["date_fin"])
        prequalification_infos.append(prequalification_info)
        employee_support_periods.setdefault(employee_info["id"], []).append(
            (prequalification_info["date_debut"], prequalification_info["date_fin"])
        )

    code_to_criteria = {
        criteria.api_code: criteria for criteria in GEIQAdministrativeCriteria.objects.exclude(api_code="")
    }
    for employee_info in employee_infos.values():
        support_days_nb = _nb_days(employee_support_periods[employee_info["id"]], year=assessment.campaign.year)
        employee_info.update(
            _compute_eligibility_fields(
                {statut["libelle_abr"] for statut in employee_info["statuts_prioritaire"]},
                code_to_criteria,
                support_days_nb,
            )
        )
        employee_info["support_days_nb"] = support_days_nb

    # Sync data to DB

    def employee_data_to_django(data, *, mapping, model):
        employee = label_data_to_django(data, mapping=mapping, model=model)
        employee.assessment = assessment
        return employee

    sync_to_db(
        employee_infos.values(),
        models.Employee.objects.filter(assessment=assessment).all(),
        model=models.Employee,
        mapping=EMPLOYEE_MAPPING,
        data_to_django_obj=employee_data_to_django,
        with_delete=True,
    )

    label_id_to_employee = {employee.label_id: employee for employee in assessment.employees.all()}

    def contract_data_to_django(data, *, mapping, model):
        contract = label_data_to_django(data, mapping=mapping, model=model)
        contract.employee = label_id_to_employee[data["salarie"]]
        return contract

    sync_to_db(
        contract_infos,
        models.EmployeeContract.objects.filter(employee__assessment=assessment).all(),
        model=models.EmployeeContract,
        mapping=CONTRACT_MAPPING,
        data_to_django_obj=contract_data_to_django,
        with_delete=True,
    )

    def prequalification_data_to_django(data, *, mapping, model):
        prequalification = label_data_to_django(data, mapping=mapping, model=model)
        prequalification.employee = label_id_to_employee[data["salarie"]]
        return prequalification

    sync_to_db(
        prequalification_infos,
        models.EmployeePrequalification.objects.filter(employee__assessment=assessment).all(),
        model=models.EmployeePrequalification,
        mapping=PREQUALIFICATION_MAPPING,
        data_to_django_obj=prequalification_data_to_django,
        with_delete=True,
    )

    assessment.last_synced_at = timezone.now()
    assessment.save(update_fields={"last_synced_at"})
