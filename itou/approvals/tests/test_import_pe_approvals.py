import datetime
import io

from django.core import management
from django.test import TransactionTestCase

from itou.approvals.models import PoleEmploiApproval


TEST_FILE_PATH = "itou/approvals/tests/liste-agrements-22_03-fake.xlsx"


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
        self.assertEqual(
            output,
            [
                "Ready to import up to length=4 approvals from "
                "file=itou/approvals/tests/liste-agrements-22_03-fake.xlsx\n",
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
            ],
        )
        self.assertEqual(
            errput,
            [
                "> canceled approval found AGR_DEC=592292010007 NOM=BAUDRICOURT PRENOM=ANTOINE, skipping...\n",
                "! invalid NUM_AGR_DEC=80222012208 len=11, skipping…\n",
                "! unable to parse PRENOM_BENE=nan err=instance, skipping…\n",
            ],
        )

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
        self.assertEqual(len(approvals), 1)
        pe_approval = approvals[0]
        self.assertEqual(pe_approval.pe_structure_code, "80022")
        self.assertEqual(pe_approval.pole_emploi_id, "0009966M")
        self.assertEqual(pe_approval.number, "666112110666")
        self.assertEqual(pe_approval.first_name, "BOLOGNESE")
        self.assertEqual(pe_approval.last_name, "SPAGHETTI")
        self.assertEqual(pe_approval.birth_name, "SPAGHETTI")
        self.assertEqual(pe_approval.birthdate, datetime.date(1975, 5, 21))
        self.assertEqual(pe_approval.start_at, datetime.date(2021, 4, 8))
        self.assertEqual(pe_approval.end_at, datetime.date(2023, 4, 8))

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
        self.assertEqual(len(approvals), 1)
