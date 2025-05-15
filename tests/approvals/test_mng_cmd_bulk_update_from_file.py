import os
from tempfile import NamedTemporaryFile

import openpyxl
from dateutil.relativedelta import relativedelta
from django.core import management
from django.utils import timezone
from freezegun import freeze_time

from itou.employee_record.enums import Status
from itou.utils.export import generate_excel_sheet
from tests.approvals.factories import ProlongationFactory, SuspensionFactory
from tests.companies.factories import CompanyFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory


@freeze_time("2025-05-16", tick=False)
def test_bulk_update_from_file(caplog, tmp_path, settings):
    settings.EXPORT_DIR = tmp_path
    company = CompanyFactory()
    company_activated_at = timezone.datetime(2025, 2, 16)
    now = timezone.now()
    before_company_was_activated = company_activated_at - relativedelta(months=1)
    after_company_was_activated = company_activated_at + relativedelta(months=1)

    with freeze_time(after_company_was_activated):
        # Sent today
        job_application_nominal_case = JobApplicationFactory(
            to_company_id=company.pk,
            with_approval=True,
        )

        too_many_job_applications = JobApplicationFactory(
            to_company_id=company.pk,
            with_approval=True,
        )
        JobApplicationFactory(
            to_company_id=company.pk,
            with_approval=True,
            approval=too_many_job_applications.approval,
            job_seeker=too_many_job_applications.job_seeker,
        )

        job_application_with_suspension = JobApplicationFactory(to_company_id=company.pk, with_approval=True)
        SuspensionFactory(
            siae_id=company.pk,
            approval_id=job_application_with_suspension.approval_id,
            start_at=job_application_with_suspension.approval.start_at,
        )
        job_application_with_prolongation = JobApplicationFactory(to_company_id=company.pk, with_approval=True)
        ProlongationFactory(
            declared_by_siae_id=company.pk,
            approval_id=job_application_with_prolongation.approval_id,
            start_at=job_application_with_prolongation.approval.end_at,
        )
        job_application_integrated = JobApplicationFactory(to_company_id=company.pk, with_approval=True)
        EmployeeRecordFactory(
            job_application=job_application_integrated,
            asp_id=job_application_integrated.to_company.convention.asp_id,
            approval_number=job_application_integrated.approval.number,
            status=Status.PROCESSED,
        )

    with freeze_time(before_company_was_activated):
        job_application_beforehand_approval = JobApplicationFactory(
            to_company_id=company.pk,
            with_approval=True,
        )

    new_start_date = timezone.datetime(2025, 2, 1, tzinfo=timezone.get_current_timezone())
    new_start_date_str = new_start_date.strftime("%d/%m/%Y")
    columns = ["Nom", "Prénom", "Date de naissance", "Début de CDDI", "PASS IAE"]
    rows = [
        # Nominal case
        [
            job_application_nominal_case.job_seeker.last_name,
            job_application_nominal_case.job_seeker.first_name,
            job_application_nominal_case.job_seeker.jobseeker_profile.birthdate,
            new_start_date_str,
            job_application_nominal_case.approval.number,
        ],
        # Already began PASS IAE
        [
            job_application_beforehand_approval.job_seeker.last_name,
            job_application_beforehand_approval.job_seeker.first_name,
            job_application_beforehand_approval.job_seeker.jobseeker_profile.birthdate,
            new_start_date_str,
            job_application_beforehand_approval.approval.number,
        ],
        # Suspensions exists
        [
            job_application_with_suspension.job_seeker.last_name,
            job_application_with_suspension.job_seeker.first_name,
            job_application_with_suspension.job_seeker.jobseeker_profile.birthdate,
            new_start_date_str,
            job_application_with_suspension.approval.number,
        ],
        # Polongation exists
        [
            job_application_with_prolongation.job_seeker.last_name,
            job_application_with_prolongation.job_seeker.first_name,
            job_application_with_prolongation.job_seeker.jobseeker_profile.birthdate,
            new_start_date_str,
            job_application_with_prolongation.approval.number,
        ],
        # Integrated by the ASP
        [
            job_application_integrated.job_seeker.last_name,
            job_application_integrated.job_seeker.first_name,
            job_application_integrated.job_seeker.jobseeker_profile.birthdate,
            new_start_date_str,
            job_application_integrated.approval.number,
        ],
        # Approval not found.
        [
            "Someone",
            "I know",
            "12/12/2005",
            new_start_date_str,
            "XXXX99991111",
        ],
        # More than one accepted job application.
        [
            too_many_job_applications.job_seeker.last_name,
            too_many_job_applications.job_seeker.first_name,
            too_many_job_applications.job_seeker.jobseeker_profile.birthdate,
            new_start_date_str,
            too_many_job_applications.approval.number,
        ],
    ]
    with NamedTemporaryFile() as file:
        generate_excel_sheet(columns, rows).save(file)
        file.seek(0)
        management.call_command("bulk_update_from_file", wet_run=True, company_id=company.id, file_path=file.name)

    assert caplog.messages[:-1] == [
        "PASS pouvant être mis à jour : 2.",
        "PASS en erreur : 5.",
        "Candidatures à mettre à jour : 1",
        "Wet run! Here we go!",
        "All good!",
    ]
    path = os.path.join(settings.EXPORT_DIR, "bulk_update_from_file.xlsx")
    workbook = openpyxl.load_workbook(path)
    worksheet = workbook.active
    assert [[cell.value or "" for cell in row] for row in worksheet.rows] == [
        ["num_pass_iae", "date_debut_pass_iae", "debut_de_cddi", "pass_maj", "commentaire"],
        [
            job_application_nominal_case.approval.number,
            new_start_date_str,
            new_start_date_str,
            "True",
            "Candidature mise à jour",
        ],
        [
            job_application_beforehand_approval.approval.number,
            "16/01/2025",
            new_start_date_str,
            "False",
            "PASS IAE débutant avant la nouvelle date.",
        ],
        [
            job_application_with_suspension.approval.number,
            "16/03/2025",
            new_start_date_str,
            "False",
            "Des suspensions existent. <SuspensionQuerySet [{'start_at': "
            "datetime.date(2025, 3, 16), 'end_at': datetime.date(2028, 3, 15)}]>",
        ],
        [
            job_application_with_prolongation.approval.number,
            "16/03/2025",
            new_start_date_str,
            "False",
            "Des prolongations existent. <ProlongationQuerySet [{'start_at': "
            "datetime.date(2027, 3, 15), 'end_at': datetime.date(2027, 4, 14)}]>",
        ],
        [
            job_application_integrated.approval.number,
            "16/03/2025",
            new_start_date_str,
            "False",
            f"Fiche salarié déjà créée pour les candidatures suivantes : [UUID('{job_application_integrated.pk}')].",
        ],
        [
            "XXXX99991111",
            "",
            new_start_date_str,
            "False",
            "PASS IAE inconnu.",
        ],
        [
            too_many_job_applications.approval.number,
            new_start_date_str,
            new_start_date_str,
            "True",
            "Mise à jour de la candidature reliée au PASS impossible car il y en a plusieurs.",
        ],
    ]
    job_application_nominal_case.refresh_from_db()
    assert job_application_nominal_case.hiring_start_at == new_start_date.date()

    assert job_application_nominal_case.updated_at == now
    assert job_application_nominal_case.approval.start_at == new_start_date.date()
    assert job_application_nominal_case.approval.updated_at == now

    too_many_job_applications.refresh_from_db()
    # Job  application was not updated but approval was.
    assert too_many_job_applications.hiring_start_at == after_company_was_activated.date()
    assert too_many_job_applications.updated_at != now
    assert too_many_job_applications.approval.start_at == new_start_date.date()
    assert too_many_job_applications.approval.updated_at != job_application_nominal_case.approval.created_at

    should_not_be_updated = [
        job_application_beforehand_approval,
        job_application_with_suspension,
        job_application_with_prolongation,
        job_application_integrated,
    ]
    for obj in should_not_be_updated:
        obj.refresh_from_db()
        assert obj.hiring_start_at != new_start_date.date()
        assert obj.approval.start_at != new_start_date.date()
        assert obj.created_at == obj.updated_at
