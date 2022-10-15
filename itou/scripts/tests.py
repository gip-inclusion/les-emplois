import datetime
import io
import os
import unittest
from dataclasses import dataclass
from unittest.mock import patch

import pandas
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import management
from django.test import TestCase, TransactionTestCase

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.approvals.models import Approval, PoleEmploiApproval
from itou.asp.factories import CommuneFactory
from itou.job_applications.enums import SenderKind
from itou.job_applications.factories import JobApplicationFactory, JobApplicationSentBySiaeFactory
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.scripts.management.commands.import_ai_employees import (
    APPROVAL_COL,
    BIRTHDATE_COL,
    CITY_INSEE_COL,
    COMMENTS_COL,
    CONTRACT_ENDDATE_COL,
    CONTRACT_STARTDATE_COL,
    DATE_FORMAT,
    EMAIL_COL,
    FIRST_NAME_COL,
    LAST_NAME_COL,
    NIR_COL,
    PASS_IAE_END_DATE_COL,
    PASS_IAE_NUMBER_COL,
    PASS_IAE_START_DATE_COL,
    PHONE_COL,
    POST_CODE_COL,
    SIRET_COL,
    USER_ITOU_EMAIL_COL,
    USER_PK_COL,
    Command as ImportAiEmployeesCommand,
)
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory
from itou.users.factories import JobSeekerFactory, PrescriberFactory, UserFactory
from itou.users.models import User


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
        self.assertEqual(
            stdout.getvalue().split("\n"),
            [
                "PE approvals needing to be sent count=2",
                f"pe_approval={other_pe_approval} start_at={other_pe_approval.start_at.isoformat()} "
                "pe_state=notification_pending",
                f"pe_approval={pe_approval} start_at={pe_approval.start_at.isoformat()} "
                "pe_state=notification_should_retry",
                "",
            ],
        )
        sleep_mock.assert_called_with(3)
        self.assertEqual(sleep_mock.call_count, 2)
        self.assertEqual(notify_mock.call_count, 2)

        ignored_approval.refresh_from_db()
        self.assertEqual(ignored_approval.pe_notification_status, "notification_error")
        self.assertEqual(ignored_approval.pe_notification_exit_code, "MISSING_USER_DATA")


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
        self.assertEqual(pe_approval_1.siae_kind, "AI")
        self.assertEqual(pe_approval_1.siae_siret, "123456789")
        self.assertEqual(pe_approval_2.siae_kind, "ETTI")
        self.assertEqual(pe_approval_2.siae_siret, "123456789")


@dataclass
class AiCSVFileMock:
    """Mock the CSV file transmitted by the AFP."""

    pmo_siret: str = "33491262300058"
    pmo_denom_soc: str = "UNE NOUVELLE CHANCE"
    ppn_numero_inscription: str = "141068078200557"
    pph_nom_usage: str = "CHAMADE"
    pph_prenom: str = "SYLIA"
    pph_date_naissance: str = "1983-07-11"
    agr_numero_agrement: str = ""
    adr_point_remise: str = "app 14"
    adr_cplt_point_geo: str = "Cat's Eyes"
    codetypevoie: str = "RUE"
    adr_numero_voie: str = "5"
    codeextensionvoie: str = "B"
    adr_libelle_voie: str = "du Louvre"
    adr_cplt_distribution: str = ""
    codepostalcedex: str = "13000"
    codeinseecom: str = "13200"
    adr_telephone: str = "0622568941"
    adr_mail: str = "sylia@chamade.fr"
    ctr_date_embauche: str = "2021-08-12"
    ctr_date_fin_reelle: str = ""


@dataclass
class CleanedAiCsvFileMock(AiCSVFileMock):
    """Add expected cleaned values."""

    pph_date_naissance: datetime.datetime = datetime.datetime(1983, 7, 11)
    ctr_date_embauche: datetime.datetime = datetime.datetime(2021, 8, 12)
    nir_is_valid: bool = True
    siret_validated_by_asp: bool = True
    commentaire: str = ""


@unittest.skipUnless(os.getenv("CI", False), "It is a long management command and normally not subject to change!")
class ImportAiEmployeesManagementCommandTest(TestCase):
    """November 30th we imported AI employees.
    See users.management.commands.import_ai_employees.
    """

    fixtures = ["test_asp_INSEE_communes_factory.json"]

    @property
    def command(self):
        """
        Instantiate the command without calling call_command to make it faster.
        """
        command = ImportAiEmployeesCommand()
        command.set_logger(verbosity=0)
        command.dry_run = False
        return command

    def test_cleaning(self):
        """Test dataframe cleaning: rows formatting and validation."""
        command = self.command

        # Perfect data.
        df = pandas.DataFrame([AiCSVFileMock()])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertTrue(isinstance(row[BIRTHDATE_COL], datetime.datetime))
        self.assertTrue(isinstance(row[CONTRACT_STARTDATE_COL], datetime.datetime))
        self.assertTrue(row["nir_is_valid"])
        self.assertTrue(row["siret_validated_by_asp"])

        # Invalid birth date.
        df = pandas.DataFrame([AiCSVFileMock(**{BIRTHDATE_COL: "1668-11-09"})])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertEqual(row[BIRTHDATE_COL].strftime(DATE_FORMAT), "1968-11-09")
        self.assertTrue(isinstance(row[BIRTHDATE_COL], datetime.datetime))

        # Invalid NIR.
        df = pandas.DataFrame([AiCSVFileMock(**{NIR_COL: "56987534"})])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertEqual(row[NIR_COL], "")
        self.assertFalse(row["nir_is_valid"])

        # Excluded SIRET from the ASP.
        siret = "33491197100029"
        df = pandas.DataFrame([AiCSVFileMock(**{SIRET_COL: siret})])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertEqual(row[SIRET_COL], siret)
        self.assertFalse(row["siret_validated_by_asp"])

        # Employer email.
        domain = "unenouvellechance.fr"
        siae = SiaeFactory(auth_email=f"accueil@{domain}", kind=SiaeKind.AI)
        df = pandas.DataFrame([AiCSVFileMock(**{EMAIL_COL: f"colette@{domain}", SIRET_COL: siae.siret})])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertEqual(row[EMAIL_COL], "")

        # Generic email.
        domain = "gmail.fr"
        siae = SiaeFactory(auth_email=f"accueil@{domain}", kind=SiaeKind.AI)
        df = pandas.DataFrame([AiCSVFileMock(**{EMAIL_COL: f"colette@{domain}"})])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertEqual(row[EMAIL_COL], "colette@gmail.fr")

    def test_filter_invalid_nirs(self):
        # Create a dataframe with one valid and one invalid NIR.
        command = self.command
        df = pandas.DataFrame(
            [CleanedAiCsvFileMock(), CleanedAiCsvFileMock(**{NIR_COL: "56987534", "nir_is_valid": False})]
        )
        df, invalid_nirs_df = command.filter_invalid_nirs(df)

        # Filtered rows.
        self.assertEqual(len(df), 2)
        self.assertEqual(len(invalid_nirs_df), 1)
        self.assertFalse(invalid_nirs_df.iloc[0]["nir_is_valid"])

        # A comment has been added to invalid rows.
        expected_comment = "NIR invalide. Utilisateur potentiellement créé sans NIR."
        self.assertEqual(df.iloc[0][COMMENTS_COL], "")
        self.assertEqual(df.iloc[1][COMMENTS_COL], expected_comment)
        self.assertEqual(invalid_nirs_df.iloc[0][COMMENTS_COL], expected_comment)

    def test_remove_ignored_rows(self):
        command = self.command
        SiaeFactory(kind=SiaeKind.AI, siret=getattr(CleanedAiCsvFileMock(), SIRET_COL))

        # Ended contracts are removed.
        df = pandas.DataFrame([CleanedAiCsvFileMock(), CleanedAiCsvFileMock(**{CONTRACT_ENDDATE_COL: "2020-11-30"})])
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 1)
        expected_comment = "Ligne ignorée : contrat terminé."
        self.assertEqual(total_df.iloc[1][COMMENTS_COL], expected_comment)

        # Continue even if df.CONTRACT_ENDDATE_COL does not exists.
        df = pandas.DataFrame([CleanedAiCsvFileMock(), CleanedAiCsvFileMock(**{CONTRACT_ENDDATE_COL: "2020-11-30"})])
        df = df.drop(columns=[CONTRACT_ENDDATE_COL])
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 2)

        # SIRET provided by the ASP are removed.
        df = pandas.DataFrame(
            [
                CleanedAiCsvFileMock(),
                CleanedAiCsvFileMock(**{SIRET_COL: "33491197100029", "siret_validated_by_asp": False}),
            ]
        )
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 1)
        expected_comment = "Ligne ignorée : entreprise inexistante communiquée par l'ASP."
        self.assertEqual(total_df.iloc[1][COMMENTS_COL], expected_comment)

        # Inexistent structures are removed.
        df = pandas.DataFrame([CleanedAiCsvFileMock(), CleanedAiCsvFileMock(**{SIRET_COL: "202020202"})])
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 1)
        expected_comment = "Ligne ignorée : entreprise inexistante."
        self.assertEqual(total_df.iloc[1][COMMENTS_COL], expected_comment)

        # Rows with approvals are removed.
        df = pandas.DataFrame([CleanedAiCsvFileMock(), CleanedAiCsvFileMock(**{APPROVAL_COL: "670929"})])
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 1)
        expected_comment = "Ligne ignorée : agrément ou PASS IAE renseigné."
        self.assertEqual(total_df.iloc[1][COMMENTS_COL], expected_comment)

    def test_find_or_create_job_seeker__find(self):
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        CommuneFactory(code=getattr(CleanedAiCsvFileMock, CITY_INSEE_COL))
        command = self.command

        # Find existing user with NIR.
        nir = getattr(CleanedAiCsvFileMock(), NIR_COL)
        JobSeekerFactory(nir=nir)
        df = pandas.DataFrame([CleanedAiCsvFileMock()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertFalse(created)
        self.assertTrue(job_seeker)
        self.assertEqual(job_seeker.nir, nir)
        self.assertEqual(User.objects.all().count(), 2)
        # Clean
        job_seeker.delete()

        # Find existing user with email address.
        email = getattr(CleanedAiCsvFileMock(), EMAIL_COL)
        JobSeekerFactory(nir="", email=email)
        df = pandas.DataFrame([CleanedAiCsvFileMock()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertFalse(created)
        self.assertTrue(job_seeker)
        self.assertEqual(job_seeker.email, email)
        self.assertEqual(User.objects.all().count(), 2)
        # Clean
        job_seeker.delete()

        # Find existing user created previously by this script.
        base_data = CleanedAiCsvFileMock()
        first_name = getattr(base_data, FIRST_NAME_COL).title()
        last_name = getattr(base_data, LAST_NAME_COL).title()
        birthdate = getattr(base_data, BIRTHDATE_COL)
        nir = getattr(base_data, NIR_COL)
        JobSeekerFactory(
            first_name=first_name,
            last_name=last_name,
            birthdate=birthdate,
            nir=nir,
            created_by=developer,
            date_joined=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
        )
        df = pandas.DataFrame([CleanedAiCsvFileMock()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertFalse(created)
        self.assertTrue(job_seeker)
        self.assertEqual(job_seeker.birthdate, birthdate.date())
        self.assertEqual(User.objects.all().count(), 2)
        # Clean
        job_seeker.delete()

    def test_find_or_create_job_seeker__create(self):
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        commune = CommuneFactory(code=getattr(CleanedAiCsvFileMock, CITY_INSEE_COL))
        command = self.command

        # Job seeker not found: create user.
        df = pandas.DataFrame([CleanedAiCsvFileMock()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertTrue(created)
        self.assertTrue(job_seeker)
        self.assertEqual(User.objects.all().count(), 2)
        # Clean
        job_seeker.delete()

        # # NIR is empty: create user with NIR None, even if another one exists.
        previous_job_seekers_pk = [JobSeekerFactory(nir="").pk, JobSeekerFactory(nir=None).pk]
        df = pandas.DataFrame([CleanedAiCsvFileMock(**{NIR_COL: "", "nir_is_valid": False})])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertTrue(created)
        self.assertTrue(job_seeker)
        self.assertEqual(User.objects.all().count(), 4)
        self.assertEqual(job_seeker.nir, None)
        # Clean
        job_seeker.delete()
        User.objects.filter(pk__in=previous_job_seekers_pk).delete()

        # # If found job_seeker is not a job seeker: create one with a fake email address.
        prescriber = PrescriberFactory(email=getattr(CleanedAiCsvFileMock(), EMAIL_COL))
        df = pandas.DataFrame([CleanedAiCsvFileMock()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertTrue(created)
        self.assertTrue(job_seeker)
        self.assertEqual(User.objects.all().count(), 3)
        self.assertEqual(job_seeker.nir, getattr(CleanedAiCsvFileMock(), NIR_COL))
        self.assertNotEqual(job_seeker.email, prescriber.email)
        # Clean
        job_seeker.delete()
        prescriber.delete()

        # Check expected attributes.
        # Perfect path: NIR, email, ...
        # Created by developer on XX date.
        base_data = CleanedAiCsvFileMock()
        df = pandas.DataFrame([base_data])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertTrue(created)
        self.assertEqual(job_seeker.created_by.pk, developer.pk)
        self.assertEqual(job_seeker.date_joined, settings.AI_EMPLOYEES_STOCK_IMPORT_DATE)
        self.assertEqual(job_seeker.first_name, getattr(base_data, FIRST_NAME_COL).title())
        self.assertEqual(job_seeker.last_name, getattr(base_data, LAST_NAME_COL).title())
        self.assertEqual(job_seeker.birthdate, getattr(base_data, BIRTHDATE_COL))
        self.assertEqual(job_seeker.email, getattr(base_data, EMAIL_COL))
        self.assertTrue(job_seeker.address_line_1)
        self.assertTrue(job_seeker.address_line_2)
        self.assertEqual(job_seeker.post_code, getattr(base_data, POST_CODE_COL))
        self.assertEqual(job_seeker.city, commune.name.title())
        self.assertTrue(job_seeker.department)
        self.assertEqual(job_seeker.phone, getattr(base_data, PHONE_COL))
        self.assertEqual(job_seeker.nir, getattr(base_data, NIR_COL))
        # Clean
        job_seeker.delete()

        # If no email provided: fake email.
        df = pandas.DataFrame([CleanedAiCsvFileMock(**{EMAIL_COL: ""})])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertTrue(created)
        self.assertTrue(job_seeker.email.endswith("@email-temp.com"))
        job_seeker.delete()

        # A job seeker is found by email address but its NIR is different.
        # Create a new one.
        email = getattr(CleanedAiCsvFileMock(), EMAIL_COL)
        JobSeekerFactory(nir="141062a78200555", email=email)
        df = pandas.DataFrame([CleanedAiCsvFileMock()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertTrue(created)
        self.assertTrue(job_seeker.email.endswith("@email-temp.com"))
        job_seeker.delete()

    def test_find_or_create_approval__find(self):
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        command = self.command

        # Existing valid PASS IAE delivered after a job application has been accepted.
        approval_start_at = datetime.date(2021, 11, 10)  # Approval should start before November 30th.
        existing_approval = ApprovalFactory(
            user__nir=getattr(CleanedAiCsvFileMock(), NIR_COL), start_at=approval_start_at
        )
        created, expected_approval, _ = command.find_or_create_approval(
            job_seeker=existing_approval.user, created_by=developer
        )
        self.assertFalse(created)
        self.assertTrue(expected_approval.is_valid)
        # Make sure no update was made.
        self.assertEqual(existing_approval.pk, expected_approval.pk)
        self.assertEqual(existing_approval.start_at, expected_approval.start_at)
        self.assertEqual(existing_approval.user.pk, expected_approval.user.pk)
        # Clean
        existing_approval.user.delete()

        # PASS IAE created previously by this script.
        existing_approval = ApprovalFactory(
            user__nir=getattr(CleanedAiCsvFileMock(), NIR_COL),
            start_at=datetime.date(2021, 12, 1),
            created_by=developer,
            created_at=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
        )
        created, expected_approval, _ = command.find_or_create_approval(
            job_seeker=existing_approval.user, created_by=developer
        )
        self.assertFalse(created)
        self.assertEqual(existing_approval.pk, expected_approval.pk)
        self.assertTrue(expected_approval.is_valid)
        # Clean
        existing_approval.user.delete()

    def test_find_or_create_approval__create(self):
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        command = self.command

        # No PASS IAE.
        job_seeker = JobSeekerFactory(nir=getattr(CleanedAiCsvFileMock(), NIR_COL))
        created, approval, _ = command.find_or_create_approval(job_seeker=job_seeker, created_by=developer)
        self.assertTrue(created)
        self.assertTrue(approval.is_valid)
        # Check attributes
        self.assertEqual(approval.user.pk, job_seeker.pk)
        self.assertEqual(approval.start_at, datetime.date(2021, 12, 1))
        self.assertEqual(approval.end_at, datetime.date(2023, 11, 30))
        self.assertEqual(approval.created_by.pk, developer.pk)
        self.assertEqual(approval.created_at, settings.AI_EMPLOYEES_STOCK_IMPORT_DATE)
        self.assertTrue(approval.is_from_ai_stock)

        # Clean
        job_seeker.delete()

        # Expired PASS IAE.
        approval_start_at = datetime.date.today() - relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS, days=2)
        expired_approval = ApprovalFactory(
            user__nir=getattr(CleanedAiCsvFileMock(), NIR_COL), start_at=approval_start_at
        )
        job_seeker = expired_approval.user
        created, approval, _ = command.find_or_create_approval(job_seeker=job_seeker, created_by=developer)
        self.assertTrue(created)
        self.assertEqual(approval.user.pk, job_seeker.pk)
        self.assertTrue(approval.is_valid)
        self.assertEqual(job_seeker.approvals.count(), 2)
        # Clean
        job_seeker.delete()

        # PASS created after November 30th with a job application:
        # the employer tried to get a PASS IAE quicker.
        siae = SiaeFactory(with_membership=True)
        previous_approval = ApprovalFactory(user__nir=getattr(CleanedAiCsvFileMock(), NIR_COL))
        job_seeker = previous_approval.user
        job_application = JobApplicationSentBySiaeFactory(
            job_seeker=job_seeker,
            to_siae=siae,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval=previous_approval,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC,
        )
        created, _, redelivered_approval = command.find_or_create_approval(job_seeker=job_seeker, created_by=developer)

        # assert previous approval does not exist anymore.
        self.assertFalse(Approval.objects.filter(pk=previous_approval.pk).exists())
        # assert previous job application does not exist anymore.
        self.assertFalse(JobApplication.objects.filter(pk=job_application.pk).exists())
        # assert a new PASS IAE has been delivered.
        self.assertTrue(created)
        self.assertTrue(redelivered_approval)

        # Clean
        job_seeker.delete()

        # PASS created after November 30th with a job application but not sent by this employer.
        siae = SiaeFactory(with_membership=True)
        previous_approval = ApprovalFactory(user__nir=getattr(CleanedAiCsvFileMock(), NIR_COL))
        job_seeker = previous_approval.user
        job_application = JobApplicationSentBySiaeFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval=previous_approval,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC,
        )
        created, _, redelivered_approval = command.find_or_create_approval(job_seeker=job_seeker, created_by=developer)

        # assert previous approval does not exist anymore.
        self.assertFalse(Approval.objects.filter(pk=previous_approval.pk).exists())
        # assert previous job application does not exist anymore.
        self.assertFalse(JobApplication.objects.filter(pk=job_application.pk).exists())
        # assert a new PASS IAE has been delivered.
        self.assertTrue(created)
        self.assertTrue(redelivered_approval)

        # Clean
        job_seeker.delete()

        # Multiple accepted job applications linked to this approval. Raise an error if dry run is not set.
        siae = SiaeFactory(with_membership=True)
        previous_approval = ApprovalFactory(user__nir=getattr(CleanedAiCsvFileMock(), NIR_COL))
        job_seeker = previous_approval.user
        job_application = JobApplicationSentBySiaeFactory(
            job_seeker=job_seeker,
            to_siae=siae,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval=previous_approval,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC,
        )
        JobApplicationSentBySiaeFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval=previous_approval,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC,
        )

        created, approval, redelivered_approval = command.find_or_create_approval(
            job_seeker=job_seeker, created_by=developer
        )
        self.assertFalse(created)
        self.assertFalse(redelivered_approval)
        self.assertTrue(previous_approval.pk, approval.pk)
        job_seeker.delete()

    def test_find_or_create_job_application__find(self):
        # Find job applications created previously by this script.
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        command = self.command

        # An approval is mandatory to test employee records creation (FS).
        approval = ApprovalFactory(user__nir=getattr(CleanedAiCsvFileMock(), NIR_COL))
        expected_job_app = JobApplicationSentBySiaeFactory(
            to_siae__kind=SiaeKind.AI,
            state=JobApplicationWorkflow.STATE_ACCEPTED,  # Mandatory for FS.
            job_seeker=approval.user,
            approval=approval,
            approval_manually_delivered_by=developer,
            created_at=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
            hiring_start_at=getattr(CleanedAiCsvFileMock(), CONTRACT_STARTDATE_COL),
        )
        job_seeker = expected_job_app.job_seeker
        df = pandas.DataFrame([CleanedAiCsvFileMock(**{SIRET_COL: expected_job_app.to_siae.siret})])
        created, found_job_application, _ = command.find_or_create_job_application(
            approval=expected_job_app.approval,
            job_seeker=job_seeker,
            row=df.iloc[0],
            approval_manually_delivered_by=developer,
        )
        self.assertFalse(created)
        self.assertEqual(expected_job_app.pk, found_job_application.pk)
        self.assertFalse(found_job_application.can_be_cancelled)
        # Assert job application has been updated to block employee records creation.
        self.assertNotIn(
            found_job_application, JobApplication.objects.eligible_as_employee_record(found_job_application.to_siae)
        )

    def test_find_or_create_job_application__create(self):
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        command = self.command

        # Employers canceled the job application we created, hence removing the PASS IAE we delivered.
        # Remove those job applications and deliver a new PASS IAE.
        nir = getattr(CleanedAiCsvFileMock(), NIR_COL)
        siret = getattr(CleanedAiCsvFileMock(), SIRET_COL)
        approval = ApprovalFactory(user__nir=nir)
        df = pandas.DataFrame([CleanedAiCsvFileMock(**{SIRET_COL: siret})])
        job_application = JobApplicationSentBySiaeFactory(
            to_siae__kind=SiaeKind.AI,
            to_siae__siret=siret,
            state=JobApplicationWorkflow.STATE_CANCELLED,
            job_seeker=approval.user,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
            approval=None,
            approval_manually_delivered_by=developer,
            created_at=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
            hiring_start_at=df.iloc[0][CONTRACT_STARTDATE_COL],
        )
        created, new_job_application, cancelled_job_app_deleted = command.find_or_create_job_application(
            approval=approval,
            job_seeker=job_application.job_seeker,
            row=df.iloc[0],
            approval_manually_delivered_by=developer,
        )
        self.assertTrue(created)
        self.assertTrue(cancelled_job_app_deleted)
        # Assert employee records creation is blocked.
        self.assertNotIn(
            new_job_application, JobApplication.objects.eligible_as_employee_record(new_job_application.to_siae)
        )
        self.assertEqual(new_job_application.approval.pk, approval.pk)
        self.assertFalse(JobApplication.objects.filter(pk=job_application.pk).exists())
        self.assertFalse(new_job_application.can_be_cancelled)
        self.assertTrue(new_job_application.is_from_ai_stock)
        self.assertEqual(JobApplication.objects.count(), 1)
        job_application.job_seeker.delete()

        # Different contract starting date.
        nir = getattr(CleanedAiCsvFileMock(), NIR_COL)
        approval = ApprovalFactory(user__nir=nir)
        siae = SiaeFactory(kind=SiaeKind.AI)
        job_application = JobApplicationFactory(
            to_siae=siae,
            sender_siae=siae,
            job_seeker=approval.user,
            approval=approval,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
            approval_manually_delivered_by=developer,
            created_at=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
            hiring_start_at=datetime.date(2021, 1, 1),
        )
        df = pandas.DataFrame([CleanedAiCsvFileMock(**{SIRET_COL: siae.siret})])
        created, new_job_application, cancelled_job_app_deleted = command.find_or_create_job_application(
            approval=job_application.approval,
            job_seeker=job_application.job_seeker,
            row=df.iloc[0],
            approval_manually_delivered_by=developer,
        )
        self.assertTrue(created)
        self.assertNotEqual(job_application.pk, new_job_application.pk)
        self.assertFalse(cancelled_job_app_deleted)
        job_application.job_seeker.delete()

    def test_import_data_into_itou(self):
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        CommuneFactory(code=getattr(CleanedAiCsvFileMock, CITY_INSEE_COL))
        command = self.command
        base_data = CleanedAiCsvFileMock()
        siae = SiaeFactory(siret=getattr(base_data, SIRET_COL), kind=SiaeKind.AI)

        # User, approval and job application creation.
        input_df = pandas.DataFrame([base_data])
        output_df = command.import_data_into_itou(df=input_df, to_be_imported_df=input_df)
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(Approval.objects.count(), 1)
        self.assertEqual(JobApplication.objects.count(), 1)
        job_seeker = User.objects.filter(is_job_seeker=True).get()
        self.assertEqual(job_seeker.job_applications.count(), 1)
        self.assertEqual(job_seeker.approvals.count(), 1)
        job_seeker.delete()

        # User, approval and job application retrieval.
        job_seeker = JobSeekerFactory(nir=getattr(base_data, NIR_COL))
        ApprovalFactory(user=job_seeker)
        JobApplicationFactory(
            sender_kind=SenderKind.SIAE_STAFF,
            sender_siae=siae,
            to_siae=siae,
            created_at=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
            approval_manually_delivered_by=developer,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
            job_seeker=job_seeker,
            hiring_start_at=getattr(base_data, CONTRACT_STARTDATE_COL),
        )
        input_df = pandas.DataFrame([CleanedAiCsvFileMock()])
        output_df = command.import_data_into_itou(df=input_df, to_be_imported_df=input_df)
        self.assertEqual(User.objects.filter(is_job_seeker=True).count(), 1)
        self.assertEqual(Approval.objects.count(), 1)
        self.assertEqual(JobApplication.objects.count(), 1)
        job_seeker.delete()

        # Only values to be imported are imported but the whole input data frame
        # is updated for logging purposes.
        input_df = pandas.DataFrame(
            [
                CleanedAiCsvFileMock(**{CONTRACT_ENDDATE_COL: "2020-05-11"}),  # Ended contracts are ignored.
                CleanedAiCsvFileMock(**{SIRET_COL: "598742121322354"}),  # Not existing SIAE.
                CleanedAiCsvFileMock(
                    **{
                        NIR_COL: "141062a78200555",
                        EMAIL_COL: "tartarin@gmail.fr",
                        BIRTHDATE_COL: datetime.date(1997, 3, 12),
                    }
                ),
                # Different contract start date.
                CleanedAiCsvFileMock(**{CONTRACT_STARTDATE_COL: datetime.date(2020, 4, 12)}),
                CleanedAiCsvFileMock(),
            ]
        )
        input_df = command.add_columns_for_asp(input_df)
        input_df, to_be_imported_df = command.remove_ignored_rows(input_df)
        output_df = command.import_data_into_itou(df=input_df, to_be_imported_df=to_be_imported_df)

        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(Approval.objects.count(), 2)
        self.assertEqual(JobApplication.objects.count(), 3)

        job_seeker = User.objects.get(email=getattr(base_data, EMAIL_COL))
        self.assertEqual(job_seeker.job_applications.count(), 2)
        self.assertEqual(job_seeker.approvals.count(), 1)

        # Different contract start date.
        job_seeker = User.objects.get(email="tartarin@gmail.fr")
        self.assertEqual(job_seeker.job_applications.count(), 1)
        self.assertEqual(job_seeker.approvals.count(), 1)

        # Ignored rows.
        for _, row in output_df[:2].iterrows():
            self.assertTrue(row[COMMENTS_COL])
            self.assertFalse(row[PASS_IAE_NUMBER_COL])
            self.assertFalse(row[USER_PK_COL])

        for _, row in output_df[2:].iterrows():
            job_seeker = User.objects.get(nir=row[NIR_COL])
            approval = job_seeker.approvals.first()
            self.assertEqual(row[PASS_IAE_NUMBER_COL], approval.number)
            self.assertEqual(row[PASS_IAE_START_DATE_COL], approval.start_at.strftime(DATE_FORMAT))
            self.assertEqual(row[PASS_IAE_END_DATE_COL], approval.end_at.strftime(DATE_FORMAT))
            self.assertEqual(row[USER_PK_COL], job_seeker.jobseeker_hash_id)
            self.assertEqual(row[USER_ITOU_EMAIL_COL], job_seeker.email)

        # Clean
        job_seeker = User.objects.get(nir=getattr(base_data, NIR_COL))
        job_seeker.delete()
        job_seeker = User.objects.get(email="tartarin@gmail.fr")
        job_seeker.delete()

        # If transaction: raise and pass.
        job_seeker = JobSeekerFactory(nir=getattr(CleanedAiCsvFileMock(), NIR_COL))
        future_date = datetime.date.today() + relativedelta(months=2)
        ApprovalFactory(user=job_seeker, start_at=future_date)
        input_df = pandas.DataFrame(
            [
                base_data,
                CleanedAiCsvFileMock(
                    **{
                        NIR_COL: "141062a78200555",
                        EMAIL_COL: "tartarin@gmail.fr",
                        BIRTHDATE_COL: datetime.date(1997, 3, 12),
                    }
                ),
            ]
        )

        output_df = None
        output_df = command.import_data_into_itou(df=input_df, to_be_imported_df=input_df)
        self.assertEqual(len(output_df), 2)
