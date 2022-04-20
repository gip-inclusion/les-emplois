from dateutil.relativedelta import relativedelta
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.factories import InstitutionFactory, InstitutionWith2MembershipFactory
from itou.institutions.models import Institution
from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication, JobApplicationQuerySet, JobApplicationWorkflow
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.factories import EvaluatedSiaeFactory, EvaluationCampaignFactory
from itou.siae_evaluations.models import (
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
    create_campaigns,
    select_min_max_job_applications,
    validate_institution,
)
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.siaes.models import Siae
from itou.users.factories import JobSeekerFactory
from itou.utils.perms.user import KIND_SIAE_STAFF, UserInfo


class EvaluationCampaignMiscMethodsTest(TestCase):
    def test_select_min_max_job_applications(self):
        siae = SiaeFactory()

        # zero job application
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae))
        self.assertIsInstance(qs, JobApplicationQuerySet)
        self.assertEqual(0, qs.count())

        # less than mininum number of job applications made by SIAE (10)
        JobApplicationFactory.create_batch(
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN - 1, to_siae=siae
        )
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae))
        self.assertEqual(0, qs.count())

        # mininum number of job applications made by SIAE (10)
        JobApplicationFactory(to_siae=siae)
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae))
        self.assertEqual(2, qs.count())

        # maximum number of selectionnable job applications made by SIAE (100)
        JobApplicationFactory.create_batch(
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MAX
            - evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
            to_siae=siae,
        )
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae))
        self.assertEqual(evaluation_enums.EvaluationJobApplicationsBoundariesNumber.SELECTED_MAX, qs.count())

        # more than maximum number of selectionnable job applications made by SIAE (100)
        JobApplicationFactory.create_batch(20, to_siae=siae)
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae))
        self.assertEqual(evaluation_enums.EvaluationJobApplicationsBoundariesNumber.SELECTED_MAX, qs.count())


class EvaluationCampaignQuerySetTest(TestCase):
    def test_for_institution(self):
        institution1 = InstitutionFactory()
        EvaluationCampaignFactory(institution=institution1)

        institution2 = InstitutionFactory()
        now = timezone.now()
        EvaluationCampaignFactory(
            institution=institution2,
            evaluated_period_start_at=now.date() - relativedelta(months=9),
            evaluated_period_end_at=now.date() - relativedelta(months=8),
        )
        EvaluationCampaignFactory(
            institution=institution2,
            evaluated_period_start_at=now.date() - relativedelta(months=7),
            evaluated_period_end_at=now.date() - relativedelta(months=6),
        )
        created_at_idx0 = EvaluationCampaign.objects.for_institution(institution2)[0].evaluated_period_end_at
        created_at_idx1 = EvaluationCampaign.objects.for_institution(institution2)[1].evaluated_period_end_at
        self.assertEqual(3, EvaluationCampaign.objects.all().count())
        self.assertEqual(2, EvaluationCampaign.objects.for_institution(institution2).count())
        self.assertTrue(created_at_idx0 > created_at_idx1)

    def test_in_progress(self):
        institution = InstitutionFactory()
        self.assertEqual(0, EvaluationCampaign.objects.all().count())
        self.assertEqual(0, EvaluationCampaign.objects.in_progress().count())

        now = timezone.now()
        sometimeago = now - relativedelta(months=2)
        EvaluationCampaignFactory(
            institution=institution,
            ended_at=sometimeago,
        )
        EvaluationCampaignFactory(
            institution=institution,
        )
        self.assertEqual(2, EvaluationCampaign.objects.all().count())
        self.assertEqual(1, EvaluationCampaign.objects.in_progress().count())


class EvaluationCampaignManagerTest(TestCase):
    def test_institution_with_campaign_in_progress(self):
        institution = InstitutionFactory()
        EvaluationCampaignFactory(institution=institution)
        self.assertTrue(EvaluationCampaign.objects.has_active_campaign(institution))

    def test_institution_without_any_campaign(self):
        institution = InstitutionFactory()
        self.assertFalse(EvaluationCampaign.objects.has_active_campaign(institution))

    def test_institution_with_ended_campaign(self):
        ended_at = timezone.now() - relativedelta(years=1)
        institution = InstitutionFactory()
        EvaluationCampaignFactory(institution=institution, ended_at=ended_at)
        self.assertFalse(EvaluationCampaign.objects.has_active_campaign(institution))

    def test_institution_with_ended_and_in_progress_campaign(self):
        now = timezone.now()
        ended_at = now - relativedelta(years=1)
        institution = InstitutionFactory()
        EvaluationCampaignFactory(
            institution=institution,
            ended_at=ended_at,
        )
        EvaluationCampaignFactory(
            institution=institution,
        )
        self.assertTrue(EvaluationCampaign.objects.has_active_campaign(institution))

    def test_first_active_campaign(self):
        institution = InstitutionFactory()
        now = timezone.now()
        EvaluationCampaignFactory(institution=institution, ended_at=timezone.now())
        EvaluationCampaignFactory(
            institution=institution,
            evaluated_period_start_at=now.date() - relativedelta(months=11),
            evaluated_period_end_at=now.date() - relativedelta(months=10),
        )
        EvaluationCampaignFactory(
            institution=institution,
            evaluated_period_start_at=now.date() - relativedelta(months=6),
            evaluated_period_end_at=now.date() - relativedelta(months=5),
        )
        self.assertEqual(
            now.date() - relativedelta(months=5),
            EvaluationCampaign.objects.first_active_campaign(institution).evaluated_period_end_at,
        )

    def test_validate_institution(self):

        with self.assertRaises(ValidationError):
            validate_institution(0)

        for kind in [k for k in Institution.Kind if k != Institution.Kind.DDETS]:
            with self.subTest(kind=kind):
                institution = InstitutionFactory(kind=kind)
                with self.assertRaises(ValidationError):
                    validate_institution(institution.id)

    def test_clean(self):
        now = timezone.now()
        institution = InstitutionFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution)

        evaluation_campaign.evaluated_period_start_at = now.date()
        evaluation_campaign.evaluated_period_end_at = now.date()
        with self.assertRaises(ValidationError):
            evaluation_campaign.clean()

        evaluation_campaign.evaluated_period_start_at = now.date()
        evaluation_campaign.evaluated_period_end_at = now.date() - relativedelta(months=6)
        with self.assertRaises(ValidationError):
            evaluation_campaign.clean()

    def test_create_campaigns(self):
        evaluated_period_start_at = timezone.now() - relativedelta(months=2)
        evaluated_period_end_at = timezone.now() - relativedelta(months=1)
        ratio_selection_end_at = timezone.now() + relativedelta(months=1)

        # not DDETS
        for kind in [k for k in Institution.Kind if k != Institution.Kind.DDETS]:
            with self.subTest(kind=kind):
                institution = InstitutionFactory(kind=kind)
                self.assertEqual(
                    0, create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at)
                )

        # institution DDETS
        institution = InstitutionWith2MembershipFactory(kind=Institution.Kind.DDETS)
        self.assertEqual(
            1,
            create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at),
        )
        self.assertEqual(
            EvaluationCampaign.objects.filter(institution=institution).first(),
            EvaluationCampaign.objects.first(),
        )

    def test_eligible_job_applications(self):
        evaluation_campaign = EvaluationCampaignFactory()
        siae = SiaeFactory(department="14")
        siae2 = SiaeFactory(department="14")

        # Job Application without approval
        JobApplicationWithApprovalFactory(
            to_siae=siae,
            sender_siae=siae,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )
        self.assertEqual(0, len(evaluation_campaign.eligible_job_applications()))

        # Job Application outside institution department
        siae12 = SiaeFactory(department="12")
        JobApplicationWithApprovalFactory(
            to_siae=siae12,
            sender_siae=siae,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        self.assertEqual(0, len(evaluation_campaign.eligible_job_applications()))

        # Job Application not eligible kind
        for kind in [k for (k, _) in Siae.KIND_CHOICES if k not in evaluation_enums.EvaluationSiaesKind.Evaluable]:
            with self.subTest(kind=kind):
                siae_wrong_kind = SiaeFactory(department="14", kind=kind)
                JobApplicationWithApprovalFactory(
                    to_siae=siae_wrong_kind,
                    sender_siae=siae_wrong_kind,
                    eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
                    eligibility_diagnosis__author_siae=siae_wrong_kind,
                    hiring_start_at=timezone.now() - relativedelta(months=2),
                )
                self.assertEqual(0, len(evaluation_campaign.eligible_job_applications()))

        # Job Application not accepted
        JobApplicationWithApprovalFactory(
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae,
            hiring_start_at=timezone.now() - relativedelta(months=2),
            state=JobApplicationWorkflow.STATE_REFUSED,
        )
        self.assertEqual(0, len(evaluation_campaign.eligible_job_applications()))

        # Job Application not in period
        JobApplicationWithApprovalFactory(
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae,
            hiring_start_at=timezone.now() - relativedelta(months=10),
        )
        self.assertEqual(0, len(evaluation_campaign.eligible_job_applications()))

        # Eligibility Diagnosis not made by Siae_staff
        JobApplicationWithApprovalFactory(
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER,
            eligibility_diagnosis__author_siae=siae,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )
        self.assertEqual(0, len(evaluation_campaign.eligible_job_applications()))

        # Eligibility Diagnosis made by an other siae (not the on of the job application)
        JobApplicationWithApprovalFactory(
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae2,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )
        self.assertEqual(0, len(evaluation_campaign.eligible_job_applications()))

        # the eligible job application
        JobApplicationWithApprovalFactory(
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )
        self.assertEqual(
            JobApplication.objects.filter(
                to_siae=siae,
                sender_siae=siae,
                eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
                eligibility_diagnosis__author_siae=siae,
                hiring_start_at=timezone.now() - relativedelta(months=2),
            )[0],
            evaluation_campaign.eligible_job_applications()[0],
        )
        self.assertEqual(1, len(evaluation_campaign.eligible_job_applications()))

    def test_eligible_siaes(self):

        evaluation_campaign = EvaluationCampaignFactory()
        siae1 = SiaeFactory(department="14")
        JobApplicationWithApprovalFactory(
            to_siae=siae1,
            sender_siae=siae1,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae1,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )
        siae2 = SiaeFactory(department="14")
        JobApplicationWithApprovalFactory.create_batch(
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
            to_siae=siae2,
            sender_siae=siae2,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae2,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )
        eligible_siaes_res = evaluation_campaign.eligible_siaes()
        self.assertEqual(1, eligible_siaes_res.count())
        self.assertIn(
            {"to_siae": siae2.id, "to_siae_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN},
            eligible_siaes_res,
        )

    def test_number_of_siaes_to_select(self):
        evaluation_campaign = EvaluationCampaignFactory()
        self.assertEqual(0, evaluation_campaign.number_of_siaes_to_select())

        for i in range(3):
            siae = SiaeFactory(department="14")
            JobApplicationWithApprovalFactory.create_batch(
                evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
                to_siae=siae,
                sender_siae=siae,
                eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
                eligibility_diagnosis__author_siae=siae,
                hiring_start_at=timezone.now() - relativedelta(months=2),
            )
            self.assertEqual(1, evaluation_campaign.number_of_siaes_to_select())

        for i in range(3):
            siae = SiaeFactory(department="14")
            JobApplicationWithApprovalFactory.create_batch(
                evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
                to_siae=siae,
                sender_siae=siae,
                eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
                eligibility_diagnosis__author_siae=siae,
                hiring_start_at=timezone.now() - relativedelta(months=2),
            )
        self.assertEqual(2, evaluation_campaign.number_of_siaes_to_select())

    def test_eligible_siaes_under_ratio(self):
        evaluation_campaign = EvaluationCampaignFactory()

        for i in range(6):
            siae = SiaeFactory(department="14")
            JobApplicationWithApprovalFactory.create_batch(
                evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
                to_siae=siae,
                sender_siae=siae,
                eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
                eligibility_diagnosis__author_siae=siae,
                hiring_start_at=timezone.now() - relativedelta(months=2),
            )
        self.assertEqual(2, evaluation_campaign.eligible_siaes_under_ratio().count())
