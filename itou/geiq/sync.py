import datetime
import logging

from django.utils import timezone

from itou.geiq_assessments import models as geiq_assessments_models
from itou.users.enums import Title
from itou.utils.apis import geiq_label
from itou.utils.sync import DiffItemKind, yield_sync_diff


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


def get_geiq_infos():
    FIELDS = ("id", "nom", "siret", "ville", "cp")
    client = geiq_label.get_client()

    geiq_infos = []
    for geiq in client.get_all_geiq():
        geiq_info = {k: geiq[k] for k in FIELDS}
        geiq_info["antennes"] = []
        for antenne in geiq["antennes"]:
            geiq_info["antennes"].append({k: antenne[k] for k in FIELDS})
        geiq_infos.append(geiq_info)
    return geiq_infos


EMPLOYEE_MAPPING = {
    "label_id": "id",
    "last_name": "nom",
    "first_name": "prenom",
    "title": "sexe",
    "birthdate": "date_naissance",
    "allowance_amount": "montant_aide",
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


def _nb_days_in_year(start: datetime.date, end: datetime.date, *, year: int):
    if start.year < year:
        start = datetime.date(year, 1, 1)
    elif start.year > year:
        # This shouldn't happen
        return 0
    if end.year < year:
        return 0
    elif end.year > year:
        end = datetime.date(year, 12, 31)
    return (end - start).days + 1


def sync_employee_and_contracts(assessment):
    assessment_antenna_ids = []
    assert not assessment.contracts_synced_at
    # Prevent concurrent sync on the same assessment
    assessment = geiq_assessments_models.Assessment.objects.select_for_update().get(pk=assessment.pk)
    if assessment.contracts_synced_at:
        logger.info(
            "Assessment pk=%s: contract already synced at %s - aborting",
            assessment.pk,
            assessment.contracts_synced_at,
        )
        return
    geiq_id = assessment.label_geiq_id
    Employee = geiq_assessments_models.Employee
    EmployeeContract = geiq_assessments_models.EmployeeContract
    EmployeePrequalification = geiq_assessments_models.EmployeePrequalification
    assessment_antenna_ids = (
        [antenna["id"] for antenna in assessment.label_antennas] if assessment.label_antennas else []
    )
    if assessment.with_main_geiq:
        assessment_antenna_ids.append(0)  # 0 means the main GEIQ in Label contracts's infos
    client = geiq_label.get_client()

    contract_infos = []
    prequalification_infos = []
    employee_infos = {}
    employee_support_periods = {}
    employees_in_assessment_year = set()

    limit_end_date = datetime.date(assessment.campaign.year - 1, 10, 1)
    label_rates = client.get_taux_geiq(geiq_id=geiq_id)[0]
    # TODO: rajouter filtre sur antennes ?
    for contract_info in client.get_all_contracts(geiq_id, date_fin=limit_end_date - datetime.timedelta(days=1)):
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
        if end_date < limit_end_date:
            # Ignoring contract ending before assessment year
            continue
        if contract_info["antenne"]["id"] not in assessment_antenna_ids:
            # Contract on other antenna
            continue

        employee_info = contract_info["salarie"]
        if end_date >= datetime.date(assessment.campaign.year, 1, 1):
            employees_in_assessment_year.add(employee_info["id"])

        _cleanup_employee_info(employee_info)
        if employee_info["id"] in employee_infos:
            # Check consistency between contracts
            assert employee_infos[employee_info["id"]] == employee_info, (
                f"{employee_info} != {employee_infos[employee_info['id']]}"
            )
        else:
            employee_infos[employee_info["id"]] = employee_info
        contract_info["salarie"] = employee_info["id"]
        contract_infos.append(contract_info)
        employee_support_periods.setdefault(employee_info["id"], []).append((contract_info["date_debut"], end_date))

    prequalif_limit_end_date = datetime.date(assessment.campaign.year - 2, 1, 1)

    for prequalification_info in client.get_all_prequalifications(geiq_id):
        employee_info = prequalification_info["salarie"]
        _cleanup_employee_info(employee_info)
        if employee_info["id"] in employee_infos:
            # Check consistency between contracts & prequalifications
            assert employee_infos[employee_info["id"]] == employee_info, (
                f"{employee_info} != {employee_infos[employee_info['id']]}"
            )
        else:
            # Ignore prequalifications for employees without active contract in assessment year
            continue
        prequalification_info["salarie"] = employee_info["id"]
        prequalification_info["date_debut"] = convert_iso_datetime_to_date(prequalification_info["date_debut"])
        prequalification_info["date_fin"] = convert_iso_datetime_to_date(prequalification_info["date_fin"])
        if prequalification_info["date_debut"].year > assessment.campaign.year:
            # Ignoring prequalifications starting after assessment year
            continue
        if prequalification_info["date_fin"] < prequalif_limit_end_date:
            # Ignoring prequalifications ending before the year preceding the assessment
            continue
        prequalification_infos.append(prequalification_info)
        employee_support_periods.setdefault(employee_info["id"], []).append(
            (prequalification_info["date_debut"], prequalification_info["date_fin"])
        )

    # Sync data to DB
    def employee_data_to_django(data, *, mapping, model):
        employee = label_data_to_django(data, mapping=mapping, model=model)
        employee.assessment = assessment
        return employee

    sync_to_db(
        employee_infos.values(),
        Employee.objects.filter(assessment=assessment).all(),
        model=Employee,
        mapping=EMPLOYEE_MAPPING,
        data_to_django_obj=employee_data_to_django,
        with_delete=True,
    )

    label_id_to_employee = {employee.label_id: employee for employee in assessment.employees.all()}

    def contract_data_to_django(data, *, mapping, model):
        contract = label_data_to_django(data, mapping=mapping, model=model)
        contract.employee = label_id_to_employee[data["salarie"]]
        contract.allowance_granted = False
        contract.nb_days_in_campaign_year = _nb_days_in_year(
            contract.start_at,
            contract.end_at or contract.planned_end_at,
            year=assessment.campaign.year,
        )
        contract.allowance_requested = (
            contract.nb_days_in_campaign_year > geiq_assessments_models.MIN_DAYS_IN_YEAR_FOR_ALLOWANCE
        )

        return contract

    sync_to_db(
        contract_infos,
        EmployeeContract.objects.filter(employee__assessment=assessment).all(),
        model=EmployeeContract,
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
        EmployeePrequalification.objects.filter(employee__assessment=assessment).all(),
        model=EmployeePrequalification,
        mapping=PREQUALIFICATION_MAPPING,
        data_to_django_obj=prequalification_data_to_django,
        with_delete=True,
    )

    assessment.contracts_synced_at = timezone.now()
    assessment.employee_nb = len(employees_in_assessment_year)
    assessment.label_rates = label_rates
    assessment.save(update_fields={"contracts_synced_at", "employee_nb", "label_rates"})
    return assessment
