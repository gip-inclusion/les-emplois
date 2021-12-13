import datetime
from dataclasses import dataclass

import pandas
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from itou.approvals.factories import ApprovalFactory
from itou.asp.factories import CommuneFactory
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.factories import (
    JobApplicationSentByJobSeekerFactory,
    JobApplicationWithApprovalFactory,
    JobApplicationWithEligibilityDiagnosis,
)
from itou.job_applications.models import JobApplication
from itou.siaes.factories import SiaeFactory
from itou.siaes.models import Siae
from itou.users.factories import JobSeekerFactory, UserFactory
from itou.users.management.commands.import_ai_employees import (
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
    SIRET_COL,
    Command as ImportAiEmployeesCommand,
)
from itou.users.models import User


class DeduplicateJobSeekersManagementCommandsTest(TestCase):
    """
    Test the deduplication of several users.

    This is temporary and should be deleted after the release of the NIR
    which should prevent duplication.
    """

    def test_deduplicate_job_seekers(self):
        """
        Easy case : among all the duplicates, only one has a PASS IAE.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1`.
        job_app1 = JobApplicationWithApprovalFactory(job_seeker__nir=None, **kwargs)
        user1 = job_app1.job_seeker

        self.assertIsNone(user1.nir)
        self.assertEqual(1, user1.approvals.count())
        self.assertEqual(1, user1.job_applications.count())
        self.assertEqual(1, user1.eligibility_diagnoses.count())

        # Create `user2`.
        job_app2 = JobApplicationWithEligibilityDiagnosis(job_seeker__nir=None, **kwargs)
        user2 = job_app2.job_seeker

        self.assertIsNone(user2.nir)
        self.assertEqual(0, user2.approvals.count())
        self.assertEqual(1, user2.job_applications.count())
        self.assertEqual(1, user2.eligibility_diagnoses.count())

        # Create `user3`.
        job_app3 = JobApplicationWithEligibilityDiagnosis(**kwargs)
        user3 = job_app3.job_seeker
        expected_nir = user3.nir

        self.assertIsNotNone(user3.nir)
        self.assertEqual(0, user3.approvals.count())
        self.assertEqual(1, user3.job_applications.count())
        self.assertEqual(1, user3.eligibility_diagnoses.count())

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_csv=True)

        # If only one NIR exists for all the duplicates, it should
        # be reassigned to the target account.
        user1.refresh_from_db()
        self.assertEqual(user1.nir, expected_nir)

        self.assertEqual(3, user1.job_applications.count())
        self.assertEqual(3, user1.eligibility_diagnoses.count())
        self.assertEqual(1, user1.approvals.count())

        self.assertEqual(0, User.objects.filter(email=user2.email).count())
        self.assertEqual(0, User.objects.filter(email=user3.email).count())

        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user3).count())

        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user3).count())

    def test_deduplicate_job_seekers_without_empty_sender_field(self):
        """
        Easy case: among all the duplicates, only one has a PASS IAE.
        Ensure that the `sender` field is never left empty.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1` through a job application sent by him.
        job_app1 = JobApplicationSentByJobSeekerFactory(job_seeker__nir=None, **kwargs)
        user1 = job_app1.job_seeker

        self.assertEqual(1, user1.job_applications.count())
        self.assertEqual(job_app1.sender, user1)

        # Create `user2` through a job application sent by him.
        job_app2 = JobApplicationSentByJobSeekerFactory(job_seeker__nir=None, **kwargs)
        user2 = job_app2.job_seeker

        self.assertEqual(1, user2.job_applications.count())
        self.assertEqual(job_app2.sender, user2)

        # Create `user3` through a job application sent by a prescriber.
        job_app3 = JobApplicationWithEligibilityDiagnosis(job_seeker__nir=None, **kwargs)
        user3 = job_app3.job_seeker
        self.assertNotEqual(job_app3.sender, user3)
        job_app3_sender = job_app3.sender  # The sender is a prescriber.

        # Ensure that `user1` will always be the target into which duplicates will be merged
        # by attaching a PASS IAE to him.
        self.assertEqual(0, user1.approvals.count())
        self.assertEqual(0, user2.approvals.count())
        self.assertEqual(0, user3.approvals.count())
        ApprovalFactory(user=user1)

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_csv=True)

        self.assertEqual(3, user1.job_applications.count())

        job_app1.refresh_from_db()
        job_app2.refresh_from_db()
        job_app3.refresh_from_db()

        self.assertEqual(job_app1.sender, user1)
        self.assertEqual(job_app2.sender, user1)  # The sender must now be user1.
        self.assertEqual(job_app3.sender, job_app3_sender)  # The sender must still be a prescriber.

        self.assertEqual(0, User.objects.filter(email=user2.email).count())
        self.assertEqual(0, User.objects.filter(email=user3.email).count())

        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user3).count())

        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user3).count())


@dataclass
class AiCSVFile:
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
    codepostalcedex: str = "75001"
    codeinseecom: str = "75101"
    adr_telephone: str = "0622568941"
    adr_mail: str = "sylia@chamade.fr"
    ctr_date_embauche: str = "2021-08-12"
    ctr_date_fin_reelle: str = ""


@dataclass
class CleanedAiCsvFile(AiCSVFile):
    """Add expected cleaned values."""

    pph_date_naissance: datetime.datetime = datetime.datetime(1983, 7, 11)
    ctr_date_embauche: datetime.datetime = datetime.datetime(2021, 8, 12)
    nir_is_valid: bool = True
    siret_validated_by_asp: bool = True
    Commentaire: str = ""


class ImportAiEmployeesManagementCommandTest(TestCase):
    """November 30th we imported AI employees.
    See users.management.commands.import_ai_employees.
    """

    def test_cleaning(self):
        """Test dataframe cleaning: rows formatting and validation."""
        command = ImportAiEmployeesCommand()

        # Perfect data.
        df = pandas.DataFrame([AiCSVFile()])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertTrue(isinstance(row[BIRTHDATE_COL], datetime.datetime))
        self.assertTrue(isinstance(row[CONTRACT_STARTDATE_COL], datetime.datetime))
        self.assertTrue(row["nir_is_valid"])
        self.assertTrue(row["siret_validated_by_asp"])

        # Invalid birth date.
        df = pandas.DataFrame([AiCSVFile(**{BIRTHDATE_COL: "1668-11-09"})])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertEqual(row[BIRTHDATE_COL].strftime(DATE_FORMAT), "1968-11-09")
        self.assertTrue(isinstance(row[BIRTHDATE_COL], datetime.datetime))

        # Invalid NIR.
        df = pandas.DataFrame([AiCSVFile(**{NIR_COL: "56987534"})])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertEqual(row[NIR_COL], "")
        self.assertFalse(row["nir_is_valid"])

        # Excluded SIRET from the ASP.
        siret = "33491197100029"
        df = pandas.DataFrame([AiCSVFile(**{SIRET_COL: siret})])
        df = command.clean_df(df)
        row = df.iloc[0]
        self.assertEqual(row[SIRET_COL], siret)
        self.assertFalse(row["siret_validated_by_asp"])

    # Test added comments.
    def test_filter_invalid_nirs(self):
        # Create a dataframe with one valid and one invalid NIR.
        command = ImportAiEmployeesCommand()
        df = pandas.DataFrame([CleanedAiCsvFile(), CleanedAiCsvFile(**{NIR_COL: "56987534", "nir_is_valid": False})])
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

    # Test excluded rows.
    def test_remove_ignored_rows(self):
        command = ImportAiEmployeesCommand()
        command.set_logger(verbosity=0)
        SiaeFactory(kind=Siae.KIND_AI, siret=getattr(CleanedAiCsvFile(), SIRET_COL))

        # Ended contracts are removed.
        df = pandas.DataFrame([CleanedAiCsvFile(), CleanedAiCsvFile(**{CONTRACT_ENDDATE_COL: "2020-11-30"})])
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 1)
        expected_comment = "Ligne ignorée : contrat terminé."
        self.assertEqual(total_df.iloc[1][COMMENTS_COL], expected_comment)

        # SIRET provided by the ASP are removed.
        df = pandas.DataFrame(
            [CleanedAiCsvFile(), CleanedAiCsvFile(**{SIRET_COL: "33491197100029", "siret_validated_by_asp": False})]
        )
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 1)
        expected_comment = "Ligne ignorée : entreprise inexistante communiquée par l'ASP."
        self.assertEqual(total_df.iloc[1][COMMENTS_COL], expected_comment)

        # Inexistent structures are removed.
        df = pandas.DataFrame([CleanedAiCsvFile(), CleanedAiCsvFile(**{SIRET_COL: "202020202"})])
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 1)
        expected_comment = "Ligne ignorée : entreprise inexistante."
        self.assertEqual(total_df.iloc[1][COMMENTS_COL], expected_comment)

        # Rows with approvals are removed.
        df = pandas.DataFrame([CleanedAiCsvFile(), CleanedAiCsvFile(**{APPROVAL_COL: "670929"})])
        total_df, filtered_df = command.remove_ignored_rows(df)
        self.assertEqual(len(total_df), 2)
        self.assertEqual(len(filtered_df), 1)
        expected_comment = "Ligne ignorée : agrément ou PASS IAE renseigné."
        self.assertEqual(total_df.iloc[1][COMMENTS_COL], expected_comment)

    # Test importing data to Itou.

    def test_find_or_create_job_seeker__find(self):
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        CommuneFactory(code=getattr(CleanedAiCsvFile, CITY_INSEE_COL))
        command = ImportAiEmployeesCommand()
        command.set_logger(verbosity=0)
        command.dry_run = False

        # Find existing user with NIR.
        nir = getattr(CleanedAiCsvFile(), NIR_COL)
        JobSeekerFactory(nir=nir)
        df = pandas.DataFrame([CleanedAiCsvFile()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertFalse(created)
        self.assertTrue(job_seeker)
        self.assertEqual(job_seeker.nir, nir)
        self.assertEqual(User.objects.all().count(), 2)
        # Clean
        job_seeker.delete()

        # Find existing user with email address.
        email = getattr(CleanedAiCsvFile(), EMAIL_COL)
        JobSeekerFactory(nir="", email=email)
        df = pandas.DataFrame([CleanedAiCsvFile()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertFalse(created)
        self.assertTrue(job_seeker)
        self.assertEqual(job_seeker.email, email)
        self.assertEqual(User.objects.all().count(), 2)
        # Clean
        job_seeker.delete()

        # Find existing user created previously by this script.
        base_data = CleanedAiCsvFile()
        first_name = getattr(base_data, FIRST_NAME_COL).title()
        last_name = getattr(base_data, LAST_NAME_COL).title()
        birthdate = getattr(base_data, BIRTHDATE_COL)
        JobSeekerFactory(
            first_name=first_name,
            last_name=last_name,
            birthdate=birthdate,
            created_by=developer,
            date_joined=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE,
        )
        df = pandas.DataFrame([CleanedAiCsvFile()])
        created, job_seeker = command.find_or_create_job_seeker(row=df.iloc[0], created_by=developer)
        self.assertFalse(created)
        self.assertTrue(job_seeker)
        self.assertEqual(job_seeker.birthdate, birthdate.date())
        self.assertEqual(User.objects.all().count(), 2)
        # Clean
        job_seeker.delete()

    def test_find_or_create_job_seeker__create(self):
        # Job seeker not found: create user.

        # NIR is empty: create user with NIR None, even if another one exists.

        # If found job_seeker is not a job seeker: create one with no NIR and a fake email address.

        # Check expected attributes.
        # Perfect path: NIR, email, ...
        # Created by developer on XX date.

        # If no email provided: fake email.

        #
        pass

    # - Test find_or_create_approval

    # - Test find_or_create_job_applications

    # Test calling the management command.

    # Test calling command with option `--invalid-nirs-only`.
