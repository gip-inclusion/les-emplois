import datetime
import io

import openpyxl
from django.core import management
from freezegun import freeze_time

from tests.approvals.factories import ApprovalFactory
from tests.utils.test import TestCase


class ExportPEApiRejectionsTestCase(TestCase):
    @freeze_time("2022-09-13")
    def test_command_output(self):
        # generate an approval that should not be found.
        ApprovalFactory(
            pe_notification_status="notification_error",
            pe_notification_time=datetime.datetime(2022, 7, 5, tzinfo=datetime.UTC),
            pe_notification_exit_code="NOTFOUND",
        )
        approval = ApprovalFactory(
            pe_notification_status="notification_error",
            pe_notification_time=datetime.datetime(2022, 8, 31, tzinfo=datetime.UTC),
            pe_notification_exit_code="FOOBAR",
            user__last_name="Pers,e",
            user__first_name='Jul"ie',
            with_jobapplication=True,
            with_jobapplication__to_company__department=42,
            with_jobapplication__to_company__kind="EI",
            with_jobapplication__to_company__name="Ma petite entreprise",
        )
        stdout = io.StringIO()
        management.call_command("export_pe_api_rejections", stdout=stdout, stderr=io.StringIO())
        workbook = openpyxl.load_workbook("exports/2022-09-13-00-00-00-export_pe_api_rejections.xlsx")
        assert [[cell.value or "" for cell in row] for row in workbook.active.rows] == [
            [
                "numero",
                "date_notification",
                "code_echec",
                "nir",
                "pole_emploi_id",
                "nom_naissance",
                "prenom",
                "date_naissance",
                "siae_type",
                "siae_raison_sociale",
                "siae_departement",
            ],
            [
                approval.number,
                "2022-08-31 00:00:00+00:00",
                "FOOBAR",
                approval.user.nir,
                approval.user.pole_emploi_id,
                "Pers,e",
                'Jul"ie',
                str(approval.user.birthdate),
                "EI",
                "Ma petite entreprise",
                "42",
            ],
        ]
