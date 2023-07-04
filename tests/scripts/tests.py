import datetime
import io
from unittest.mock import patch

from django.core import management
from django.test import TransactionTestCase

from itou.approvals.factories import PoleEmploiApprovalFactory
from itou.approvals.models import PoleEmploiApproval
from tests.utils.test import TestCase


TEST_FILE_PATH = "itou/scripts/liste-agrements-22_03-fake.xlsx"


class PoleEmploiApprovalsSendToPeManagementTestCase(TestCase):
    @patch.object(PoleEmploiApproval, "notify_pole_emploi")
    @patch("itou.scripts.management.commands.send_pe_approvals_to_pe.sleep")
    def test_management_command(self, sleep_mock, notify_mock):
        stdout = io.StringIO()
        # create ignored PE Approvals, will not even be counted in the batch. the cron will wait for
        # the database to have the necessary job application, nir, or start date to fetch them.
        ignored_approval = PoleEmploiApprovalFactory(nir="")
        PoleEmploiApprovalFactory(nir=None)
        PoleEmploiApprovalFactory(siae_siret=None)

        # other approvals
        pe_approval = PoleEmploiApprovalFactory(
            nir="FOOBAR",
            pe_notification_status="notification_should_retry",
        )
        other_pe_approval = PoleEmploiApprovalFactory(
            nir="STUFF",
            pe_notification_status="notification_pending",
        )
        management.call_command(
            "send_pe_approvals_to_pe",
            wet_run=True,
            delay=3,
            stdout=stdout,
        )
        assert stdout.getvalue().split("\n") == [
            "PE approvals needing to be sent count=2",
            f"pe_approval={other_pe_approval} start_at={other_pe_approval.start_at.isoformat()} "
            "pe_state=notification_pending",
            f"pe_approval={pe_approval} start_at={pe_approval.start_at.isoformat()} "
            "pe_state=notification_should_retry",
            "",
        ]
        sleep_mock.assert_called_with(3)
        assert sleep_mock.call_count == 2
        assert notify_mock.call_count == 2

        ignored_approval.refresh_from_db()
        assert ignored_approval.pe_notification_status == "notification_error"
        assert ignored_approval.pe_notification_exit_code == "MISSING_USER_DATA"


class ImportPEApprovalTestCase(TransactionTestCase):
    def test_command_output(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        management.call_command(
            "import_pe_approvals", file_path=TEST_FILE_PATH, wet_run=False, stdout=stdout, stderr=stderr
        )
        stdout.seek(0)
        stderr.seek(0)
        output = stdout.readlines()
        errput = stderr.readlines()
        assert output == [
            "Ready to import up to length=4 approvals from " "file=itou/scripts/liste-agrements-22_03-fake.xlsx\n",
            "- will add number=666112110666 last_name=SPAGHETTI\n",
            "PEApprovals import summary:\n",
            "  Number of approvals, before    : 0\n",
            "  Number of approvals, after     : 0\n",
            "  Actually added approvals       : 0\n",
            "Parsing:\n",
            "  Sucessfully parsed lines       : 1\n",
            "  Unexpected parsing errors      : 1\n",
            "  Invalid approval number errors : 1\n",
            "  Canceled approvals             : 1\n",
            "Detail of expected modifications:\n",
            "  Added approvals                : 1\n",
            "  Updated approvals              : 0\n",
            "  Skipped approvals (no changes) : 0\n",
            "Done.\n",
        ]
        assert errput == [
            "> canceled approval found AGR_DEC=592292010007 NOM=BAUDRICOURT PRENOM=ANTOINE, skipping...\n",
            "! invalid NUM_AGR_DEC=80222012208 len=11, skipping…\n",
            "! unable to parse PRENOM_BENE=nan err=instance, skipping…\n",
        ]

    def test_command_write(self):
        stdout = io.StringIO()
        management.call_command("import_pe_approvals", file_path=TEST_FILE_PATH, wet_run=True, stdout=stdout)
        stdout.seek(0)
        output = stdout.readlines()[3:6]
        assert output == [
            "  Number of approvals, before    : 0\n",
            "  Number of approvals, after     : 1\n",
            "  Actually added approvals       : 1\n",
        ]
        approvals = PoleEmploiApproval.objects.all()
        assert len(approvals) == 1
        pe_approval = approvals[0]
        assert pe_approval.pe_structure_code == "80022"
        assert pe_approval.pole_emploi_id == "0009966M"
        assert pe_approval.number == "666112110666"
        assert pe_approval.first_name == "BOLOGNESE"
        assert pe_approval.last_name == "SPAGHETTI"
        assert pe_approval.birth_name == "SPAGHETTI"
        assert pe_approval.birthdate == datetime.date(1975, 5, 21)
        assert pe_approval.start_at == datetime.date(2021, 4, 8)
        assert pe_approval.end_at == datetime.date(2023, 4, 8)

        # overwrite: check idempotency
        stdout = io.StringIO()  # clear it
        management.call_command("import_pe_approvals", file_path=TEST_FILE_PATH, wet_run=True, stdout=stdout)
        stdout.seek(0)
        output = stdout.readlines()[4:7]
        assert output == [
            "  Number of approvals, before    : 1\n",
            "  Number of approvals, after     : 1\n",
            "  Actually added approvals       : 0\n",
        ]
        approvals = PoleEmploiApproval.objects.all()
        assert len(approvals) == 1


class ImportPEApprovalSiretKindTestCase(TransactionTestCase):
    def test_command_output(self):
        pe_approval_1 = PoleEmploiApprovalFactory(number="592292010007")
        pe_approval_2 = PoleEmploiApprovalFactory(number="666112110666")
        stdout = io.StringIO()
        management.call_command(
            "import_pe_approvals_siret_kind", file_path=TEST_FILE_PATH, wet_run=True, stdout=stdout
        )
        output = stdout.getvalue().split("\n")
        assert output == [
            "Ready to import up to length=4 approvals from " "file=itou/scripts/liste-agrements-22_03-fake.xlsx",
            "> pe_approval=592292010007 was updated with siret=123456789 and kind=AI",
            "! pe_approval with number=80222012208 not found",
            "! pe_approval with number=976066666688 not found",
            "> pe_approval=666112110666 was updated with siret=123456789 and kind=ETTI",
            "Done.",
            "",
        ]
        pe_approval_1.refresh_from_db()
        pe_approval_2.refresh_from_db()
        assert pe_approval_1.siae_kind == "AI"
        assert pe_approval_1.siae_siret == "123456789"
        assert pe_approval_2.siae_kind == "ETTI"
        assert pe_approval_2.siae_siret == "123456789"
