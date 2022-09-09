import datetime
import io

from django.core import management
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from itou.approvals.factories import ApprovalFactory


class ExportPEApiRejectionsTestCase(TestCase):
    @freeze_time("2022-09-13")
    def test_command_output(self):
        # generate an approval that should not be found.
        ApprovalFactory(
            pe_notification_status="notification_error",
            pe_notification_time=datetime.datetime(2022, 7, 5, tzinfo=timezone.utc),
            pe_notification_exit_code="NOTFOUND",
        )
        approval = ApprovalFactory(
            pe_notification_status="notification_error",
            pe_notification_time=datetime.datetime(2022, 8, 31, tzinfo=timezone.utc),
            pe_notification_exit_code="FOOBAR",
            user__last_name="Pers,e",
            user__first_name='Jul"ie',
        )
        stdout = io.StringIO()
        management.call_command("export_pe_api_rejections", stdout=stdout, stderr=io.StringIO())
        self.assertEqual(
            stdout.getvalue(),
            "numero,date_notification,code_echec,nir,pole_emploi_id,nom_naissance,prenom,date_naissance\n"
            + ",".join(
                map(
                    str,
                    [
                        approval.number,
                        "2022-08-31 00:00:00+00:00",
                        "FOOBAR",
                        approval.user.nir,
                        approval.user.pole_emploi_id,
                        '"Pers,e"',
                        '"Jul""ie"',
                        approval.user.birthdate,
                    ],
                )
            )
            + "\n",
        )
