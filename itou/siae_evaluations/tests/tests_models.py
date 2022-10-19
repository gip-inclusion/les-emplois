from unittest import mock

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import dateformat, timezone

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.enums import InstitutionKind
from itou.institutions.factories import InstitutionFactory, InstitutionWith2MembershipFactory
from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication, JobApplicationQuerySet, JobApplicationWorkflow
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from itou.siae_evaluations.models import (
    CampaignAlreadyPopulatedException,
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
    create_campaigns,
    select_min_max_job_applications,
    validate_institution,
)
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory, SiaeWith2MembershipsFactory
from itou.users.enums import KIND_SIAE_STAFF
from itou.users.factories import JobSeekerFactory
from itou.utils.perms.user import UserInfo


def create_batch_of_job_applications(siae):
    JobApplicationWithApprovalFactory.create_batch(
        evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
        to_siae=siae,
        sender_siae=siae,
        eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
        eligibility_diagnosis__author_siae=siae,
        hiring_start_at=timezone.now() - relativedelta(months=2),
    )


class EvaluationCampaignMiscMethodsTest(TestCase):
    def test_select_min_max_job_applications(self):
        siae = SiaeFactory()
        job_seeker = JobSeekerFactory()

        # zero job application
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae))
        self.assertIsInstance(qs, JobApplicationQuerySet)
        self.assertEqual(0, qs.count())

        # one job applications made by SIAE
        job_application = JobApplicationFactory(to_siae=siae, job_seeker=job_seeker)
        self.assertEqual(
            job_application,
            select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).first(),
        )
        self.assertEqual(1, select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count())

        # under 10 job applications, 20% is below the minimum value of 2 -> select 2
        JobApplicationFactory.create_batch(5, to_siae=siae, job_seeker=job_seeker)
        self.assertEqual(
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
            select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count(),
        )

        # from 20 job applications to 100 we have the correct percentage
        JobApplicationFactory.create_batch(55, to_siae=siae, job_seeker=job_seeker)
        self.assertEqual(
            12,
            select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count(),
        )

        # Over 100, stop at the max number -> 20
        JobApplicationFactory.create_batch(50, to_siae=siae, job_seeker=job_seeker)
        self.assertEqual(
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MAX,
            select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count(),
        )


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

        for kind in [k for k in InstitutionKind if k != InstitutionKind.DDETS]:
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
        for kind in [k for k in InstitutionKind if k != InstitutionKind.DDETS]:
            with self.subTest(kind=kind):
                InstitutionFactory(kind=kind)
                self.assertEqual(
                    0, create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at)
                )
                self.assertEqual(0, EvaluationCampaign.objects.all().count())
                self.assertEqual(len(mail.outbox), 0)

        # institution DDETS
        InstitutionWith2MembershipFactory.create_batch(2, kind=InstitutionKind.DDETS)
        self.assertEqual(
            2,
            create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at),
        )
        self.assertEqual(2, EvaluationCampaign.objects.all().count())

        # An email should have been sent to the institution members.
        self.assertEqual(len(mail.outbox), 2)
        email = mail.outbox[0]
        self.assertEqual(len(email.to), 2)
        email = mail.outbox[1]
        self.assertEqual(len(email.to), 2)

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
        for kind in [k for k in SiaeKind if k not in evaluation_enums.EvaluationSiaesKind.Evaluable]:
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

        # siae1 got 1 job application
        siae1 = SiaeFactory(department="14")
        JobApplicationWithApprovalFactory(
            to_siae=siae1,
            sender_siae=siae1,
            eligibility_diagnosis__author_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
            eligibility_diagnosis__author_siae=siae1,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        # siae2 got 2 job applications
        siae2 = SiaeFactory(department="14")
        create_batch_of_job_applications(siae2)

        # test eligible_siaes without upperbound
        eligible_siaes_res = evaluation_campaign.eligible_siaes()
        self.assertEqual(1, eligible_siaes_res.count())
        self.assertIn(
            {"to_siae": siae2.id, "to_siae_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN},
            eligible_siaes_res,
        )

        eligible_siaes_res = evaluation_campaign.eligible_siaes(upperbound=0)
        self.assertEqual(1, eligible_siaes_res.count())
        self.assertIn(
            {"to_siae": siae2.id, "to_siae_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN},
            eligible_siaes_res,
        )

        # test eligible_siaes with upperbound = 3
        eligible_siaes_res = evaluation_campaign.eligible_siaes(
            upperbound=evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN + 1
        )
        self.assertEqual(1, eligible_siaes_res.count())
        self.assertIn(
            {"to_siae": siae2.id, "to_siae_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN},
            eligible_siaes_res,
        )

        # adding 2 more job applications to siae2
        create_batch_of_job_applications(siae2)

        # test eligible_siaes without upperbound
        eligible_siaes_res = evaluation_campaign.eligible_siaes()
        self.assertEqual(1, eligible_siaes_res.count())
        self.assertIn(
            {"to_siae": siae2.id, "to_siae_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN * 2},
            eligible_siaes_res,
        )

        eligible_siaes_res = evaluation_campaign.eligible_siaes(upperbound=0)
        self.assertEqual(1, eligible_siaes_res.count())
        self.assertIn(
            {"to_siae": siae2.id, "to_siae_count": evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN * 2},
            eligible_siaes_res,
        )

        # test eligible_siaes with upperbound = 3
        eligible_siaes_res = evaluation_campaign.eligible_siaes(
            upperbound=evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN + 1
        )
        self.assertEqual(0, eligible_siaes_res.count())

    def test_number_of_siaes_to_select(self):
        evaluation_campaign = EvaluationCampaignFactory()
        self.assertEqual(0, evaluation_campaign.number_of_siaes_to_select())

        for _ in range(3):
            siae = SiaeFactory(department="14")
            create_batch_of_job_applications(siae)

        self.assertEqual(1, evaluation_campaign.number_of_siaes_to_select())

        for _ in range(3):
            siae = SiaeFactory(department="14")
            create_batch_of_job_applications(siae)

        self.assertEqual(2, evaluation_campaign.number_of_siaes_to_select())

    def test_eligible_siaes_under_ratio(self):
        evaluation_campaign = EvaluationCampaignFactory()

        for _ in range(6):
            siae = SiaeFactory(department="14")
            create_batch_of_job_applications(siae)

        self.assertEqual(2, evaluation_campaign.eligible_siaes_under_ratio().count())

    def test_populate(self):
        # integration tests
        evaluation_campaign = EvaluationCampaignFactory()
        siae = SiaeFactory(department=evaluation_campaign.institution.department, with_membership=True)
        job_seeker = JobSeekerFactory()
        user = siae.members.first()
        user_info = UserInfo(
            user=user, kind=KIND_SIAE_STAFF, siae=siae, prescriber_organization=None, is_authorized_prescriber=False
        )
        criteria1 = AdministrativeCriteria.objects.get(
            level=AdministrativeCriteria.Level.LEVEL_1, name="Bénéficiaire du RSA"
        )
        eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=[criteria1]
        )
        JobApplicationWithApprovalFactory.create_batch(
            evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis=eligibility_diagnosis,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )
        fake_now = timezone.now() - relativedelta(weeks=1)

        self.assertEqual(0, EvaluatedSiae.objects.all().count())
        self.assertEqual(0, EvaluatedJobApplication.objects.all().count())

        # first regular method exec
        evaluation_campaign.populate(fake_now)
        evaluation_campaign.refresh_from_db()

        self.assertEqual(fake_now, evaluation_campaign.percent_set_at)
        self.assertEqual(fake_now, evaluation_campaign.evaluations_asked_at)
        self.assertEqual(1, EvaluatedSiae.objects.all().count())
        self.assertEqual(2, EvaluatedJobApplication.objects.all().count())

        # check links between EvaluatedSiae and EvaluatedJobApplication
        evaluated_siae = EvaluatedSiae.objects.first()
        for evaluated_job_application in EvaluatedJobApplication.objects.all():
            with self.subTest(evaluated_job_application_pk=evaluated_job_application.pk):
                self.assertEqual(evaluated_siae, evaluated_job_application.evaluated_siae)

        # retry on populated campaign
        with self.assertRaises(CampaignAlreadyPopulatedException):
            evaluation_campaign.populate(fake_now)

    def test_transition_to_adversarial_phase(self):
        fake_now = timezone.now()
        EvaluatedSiaeFactory()  # will be ignored
        campaign = EvaluationCampaignFactory()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=campaign)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        evaluated_administrative_criterion = EvaluatedAdministrativeCriteriaFactory(
            submitted_at=fake_now,
            evaluated_job_application=evaluated_job_application
            # default review_state is PENDING
        )
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)

        # since we have a SIAE in SUBMITTED state, does not change anything
        campaign.transition_to_adversarial_phase()
        self.assertEqual(2, EvaluatedSiae.objects.filter(reviewed_at__isnull=True).count())

        # make the SIAE in another state
        evaluated_administrative_criterion.review_state = "FOOBAR"
        evaluated_administrative_criterion.save(update_fields=["review_state"])
        del evaluated_siae.state
        self.assertNotEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)

        # now the transition works
        campaign.transition_to_adversarial_phase()
        self.assertEqual(1, EvaluatedSiae.objects.filter(reviewed_at__isnull=True).count())
        evaluated_siae.refresh_from_db()
        self.assertIsNotNone(evaluated_siae.reviewed_at)

    def test_close(self):
        evaluation_campaign = EvaluationCampaignFactory()
        self.assertIsNone(evaluation_campaign.ended_at)

        evaluation_campaign.close()
        self.assertIsNotNone(evaluation_campaign.ended_at)
        ended_at = evaluation_campaign.ended_at

        evaluation_campaign.close()
        self.assertEqual(ended_at, evaluation_campaign.ended_at)


class EvaluationCampaignEmailMethodsTest(TestCase):
    def test_get_email_to_institution_ratio_to_select(self):
        institution = InstitutionWith2MembershipFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution)

        date = timezone.now().date()
        email = evaluation_campaign.get_email_to_institution_ratio_to_select(date)

        self.assertEqual(email.to, list(u.email for u in institution.active_members))
        self.assertIn(reverse("dashboard:index"), email.body)
        self.assertIn(
            f"Le choix du taux de SIAE à contrôler est possible jusqu’au {dateformat.format(date, 'd E Y')}",
            email.body,
        )
        self.assertIn(f"avant le {dateformat.format(date, 'd E Y')}", email.subject)

    def test_get_email_to_siae_selected(self):
        siae = SiaeWith2MembershipsFactory()
        evaluated_siae = EvaluatedSiaeFactory(siae=siae)
        email = evaluated_siae.get_email_to_siae_selected()

        self.assertEqual(email.to, list(u.email for u in evaluated_siae.siae.active_admin_members))
        self.assertEqual(
            email.subject,
            (
                "Contrôle a posteriori sur vos embauches réalisées "
                + f"du {dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, 'd E Y')} "
                + f"au {dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, 'd E Y')}"
            ),
        )
        self.assertIn(siae.name, email.body)
        self.assertIn(siae.kind, email.body)
        self.assertIn(siae.convention.siret_signature, email.body)
        self.assertIn(dateformat.format(timezone.now() + relativedelta(weeks=6), "d E Y"), email.body)

    def test_get_email_to_institution_selected_siae(self):
        fake_now = timezone.now()
        institution = InstitutionWith2MembershipFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution, evaluations_asked_at=fake_now)

        email = evaluation_campaign.get_email_to_institution_selected_siae()
        self.assertEqual(email.to, list(u.email for u in institution.active_members))
        self.assertIn(dateformat.format(fake_now + relativedelta(weeks=6), "d E Y"), email.body)
        self.assertIn(dateformat.format(evaluation_campaign.evaluated_period_start_at, "d E Y"), email.body)
        self.assertIn(dateformat.format(evaluation_campaign.evaluated_period_end_at, "d E Y"), email.body)


class EvaluatedSiaeQuerySetTest(TestCase):
    def test_for_siae(self):
        siae1 = SiaeFactory()
        siae2 = SiaeFactory()
        EvaluatedSiaeFactory(siae=siae2)

        self.assertEqual(0, EvaluatedSiae.objects.for_siae(siae1).count())
        self.assertEqual(1, EvaluatedSiae.objects.for_siae(siae2).count())

    def test_in_progress(self):
        fake_now = timezone.now()

        # evaluations_asked_at is None
        EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=None)
        self.assertEqual(0, EvaluatedSiae.objects.in_progress().count())

        # ended_at is not None
        EvaluatedSiaeFactory(evaluation_campaign__ended_at=fake_now)
        self.assertEqual(0, EvaluatedSiae.objects.in_progress().count())

        # evaluations_asked_at is not None, ended_at is None
        EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=fake_now, evaluation_campaign__ended_at=None)
        self.assertEqual(1, EvaluatedSiae.objects.in_progress().count())


class EvaluatedSiaeModelTest(TestCase):
    def test_state_unitary(self):
        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=fake_now)

        ## unit tests
        # no evaluated_job_application
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.PENDING, evaluated_siae.state)
        del evaluated_siae.state

        # no evaluated_administrative_criterion
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.PENDING, evaluated_siae.state)
        del evaluated_siae.state

        # one evaluated_administrative_criterion
        # empty : proof_url and submitted_at empty)
        evaluated_administrative_criteria0 = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof_url=""
        )
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.PENDING, evaluated_siae.state)
        del evaluated_siae.state

        # with proof_url
        evaluated_administrative_criteria0.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria0.save(update_fields=["proof_url"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTABLE, evaluated_siae.state)
        del evaluated_siae.state

        # PENDING + submitted_at without review
        evaluated_administrative_criteria0.submitted_at = fake_now
        evaluated_administrative_criteria0.save(update_fields=["submitted_at"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)
        del evaluated_siae.state

        # PENDING + submitted_at before review: we still consider that the DDETS can validate the documents
        evaluated_siae.reviewed_at = fake_now + relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)
        del evaluated_siae.state

        # PENDING + submitted_at after review
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)
        del evaluated_siae.state

        # with review_state REFUSED, not reviewed : removed, should not exist in real life

        # with review_state REFUSED, reviewed, submitted_at before reviewed_at
        evaluated_administrative_criteria0.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = fake_now + relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        self.assertLessEqual(evaluated_administrative_criteria0.submitted_at, evaluated_siae.reviewed_at)
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, evaluated_siae.state)
        del evaluated_siae.state

        # with review_state REFUSED, reviewed, submitted_at after reviewed_at
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        self.assertGreater(evaluated_administrative_criteria0.submitted_at, evaluated_siae.reviewed_at)
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, evaluated_siae.state)
        del evaluated_siae.state

        # with review_state REFUSED_2, reviewed, submitted_at after reviewed_at
        evaluated_administrative_criteria0.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        )
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, evaluated_siae.state)
        del evaluated_siae.state

        # with review_state REFUSED_2, reviewed, submitted_at after reviewed_at, with final_reviewed_at
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.REFUSED, evaluated_siae.state)
        del evaluated_siae.state

        # with review_state REFUSED_2, reviewed, submitted_at before reviewed_at :
        # removed, should never happen in real life

        # with review_state ACCEPTED not reviewed : removed, should not exist in real life

        # with review_state ACCEPTED reviewed, submitted_at before reviewed_at
        # : removed, should not exist in real life

        # with review_state ACCEPTED reviewed, submitted_at after reviewed_at
        evaluated_administrative_criteria0.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        )
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        review_time = fake_now - relativedelta(days=1)
        evaluated_siae.reviewed_at = review_time
        evaluated_siae.final_reviewed_at = review_time
        evaluated_siae.save(update_fields=["final_reviewed_at", "reviewed_at"])
        self.assertGreater(evaluated_administrative_criteria0.submitted_at, evaluated_siae.reviewed_at)
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ACCEPTED, evaluated_siae.state)
        del evaluated_siae.state

    def test_state_integration(self):
        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=fake_now)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory.create_batch(
            3,
            evaluated_job_application=evaluated_job_application,
            submitted_at=fake_now,
        )

        # NOT REVIEWED
        # one Pending, one Refused, one Accepted
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            2
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[2].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)
        del evaluated_siae.state

        # one Refused, two Accepted
        evaluated_siae.reviewed_at = fake_now
        evaluated_siae.save(update_fields=["reviewed_at"])
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, evaluated_siae.state)
        del evaluated_siae.state

        # three Accepted
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ACCEPTED, evaluated_siae.state)
        del evaluated_siae.state
        evaluated_siae.final_reviewed_at = None
        evaluated_siae.save(update_fields=["final_reviewed_at"])

        # REVIEWED, submitted_at less than reviewed_at
        evaluated_siae.reviewed_at = fake_now + relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])

        # one Pending, one Refused, one Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            2
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[2].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)
        del evaluated_siae.state

        # one Refused, two Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, evaluated_siae.state)
        del evaluated_siae.state

        # three Accepted
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ACCEPTED, evaluated_siae.state)
        del evaluated_siae.state
        evaluated_siae.final_reviewed_at = None
        evaluated_siae.save(update_fields=["final_reviewed_at"])

        # REVIEWED, submitted_at greater than reviewed_at
        evaluated_siae.reviewed_at = fake_now - relativedelta(days=1)
        evaluated_siae.save(update_fields=["reviewed_at"])

        # one Pending, one Refused, one Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        evaluated_administrative_criteria[
            2
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[2].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)
        del evaluated_siae.state

        # one Refused, two Accepted
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, evaluated_siae.state)
        del evaluated_siae.state

        # three Accepted
        evaluated_siae.final_reviewed_at = fake_now
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ACCEPTED, evaluated_siae.state)
        del evaluated_siae.state

    def test_state_on_closed_campaign_no_criteria(self):
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__ended_at=timezone.now())
        assert evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_not_submitted(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=1),
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_submitted(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
        )
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

    def test_state_on_closed_campaign_criteria_submitted_after_review(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=3),
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
        )
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

    def test_state_on_closed_campaign_criteria_uploaded_after_review(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=timezone.now() - relativedelta(days=3),
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            # Not submitted.
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_refused_review_not_validated(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

    def test_state_on_closed_campaign_criteria_refused_review_validated(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=timezone.now(),
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

    def test_state_on_closed_campaign_criteria_accepted(self):
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now(),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        assert evaluated_job_app.evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED

    def test_review(self):
        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__ended_at=fake_now)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            submitted_at=fake_now,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )

        evaluated_siae.review()
        evaluated_siae.refresh_from_db()
        self.assertIsNotNone(evaluated_siae.reviewed_at)

        evaluated_siae.reviewed_at = None
        evaluated_siae.save(update_fields=["reviewed_at"])

        evaluated_siae.review()
        evaluated_siae.refresh_from_db()
        self.assertIsNotNone(evaluated_siae.reviewed_at)

    def test_review_emails(self):
        fake_now = timezone.now()
        values = [
            (evaluation_enums.EvaluatedSiaeState.ACCEPTED, None, "la conformité des justificatifs"),
            (evaluation_enums.EvaluatedSiaeState.ACCEPTED, fake_now, "la conformité des nouveaux justificatifs"),
            (evaluation_enums.EvaluatedSiaeState.REFUSED, None, "un ou plusieurs justificatifs sont attendus"),
            (
                evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE,
                fake_now,
                "plusieurs de vos justificatifs n’ont pas été validés",
            ),
        ]

        for state, reviewed_at, txt in values:
            with mock.patch.object(EvaluatedSiae, "state", state):
                with self.subTest(state=state, reviewed_at=reviewed_at, txt=txt):
                    evaluated_siae = EvaluatedSiaeFactory(reviewed_at=reviewed_at)
                    evaluated_siae.review()
                    email = mail.outbox[-1]
                    self.assertIn(txt, email.body)

    def test_get_email_to_institution_submitted_by_siae(self):
        institution = InstitutionWith2MembershipFactory()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__institution=institution)
        email = evaluated_siae.get_email_to_institution_submitted_by_siae()

        self.assertIn(evaluated_siae.siae.kind, email.subject)
        self.assertIn(evaluated_siae.siae.name, email.subject)
        self.assertIn(evaluated_siae.siae.kind, email.body)
        self.assertIn(evaluated_siae.siae.name, email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), len(institution.active_members))

    def test_get_email_to_siae_reviewed(self):
        siae = SiaeFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=siae)
        email = evaluated_siae.get_email_to_siae_reviewed()

        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), len(evaluated_siae.siae.active_admin_members))
        self.assertEqual(email.to[0], evaluated_siae.siae.active_admin_members.first().email)
        self.assertIn(evaluated_siae.siae.kind, email.subject)
        self.assertIn(evaluated_siae.siae.name, email.subject)
        self.assertIn(str(evaluated_siae.siae.id), email.subject)
        self.assertIn(evaluated_siae.siae.kind, email.body)
        self.assertIn(evaluated_siae.siae.name, email.body)
        self.assertIn(str(evaluated_siae.siae.id), email.body)
        self.assertIn(evaluated_siae.evaluation_campaign.institution.name, email.body)
        self.assertIn(
            dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, "d E Y"), email.body
        )
        self.assertIn(
            dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, "d E Y"), email.body
        )
        self.assertIn("la conformité des justificatifs que vous avez", email.body)

        email = evaluated_siae.get_email_to_siae_reviewed(adversarial=True)
        self.assertIn("la conformité des nouveaux justificatifs que vous avez", email.body)

    def test_get_email_to_siae_refused(self):
        siae = SiaeFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=siae)
        email = evaluated_siae.get_email_to_siae_refused()

        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), len(evaluated_siae.siae.active_admin_members))
        self.assertEqual(email.to[0], evaluated_siae.siae.active_admin_members.first().email)
        self.assertIn(evaluated_siae.siae.kind, email.subject)
        self.assertIn(evaluated_siae.siae.name, email.subject)
        self.assertIn(str(evaluated_siae.siae.id), email.subject)
        self.assertIn(evaluated_siae.siae.kind, email.body)
        self.assertIn(evaluated_siae.siae.name, email.body)
        self.assertIn(str(evaluated_siae.siae.id), email.body)
        self.assertIn(evaluated_siae.evaluation_campaign.institution.name, email.body)
        self.assertIn(
            dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, "d E Y"), email.body
        )
        self.assertIn(
            dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, "d E Y"), email.body
        )

    def test_get_email_to_siae_adversarial_stage(self):
        siae = SiaeFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=siae)
        email = evaluated_siae.get_email_to_siae_adversarial_stage()

        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), len(evaluated_siae.siae.active_admin_members))
        self.assertEqual(email.to[0], evaluated_siae.siae.active_admin_members.first().email)
        self.assertIn(evaluated_siae.siae.kind, email.subject)
        self.assertIn(evaluated_siae.siae.name, email.subject)
        self.assertIn(str(evaluated_siae.siae.id), email.subject)
        self.assertIn(evaluated_siae.siae.kind, email.body)
        self.assertIn(evaluated_siae.siae.name, email.body)
        self.assertIn(str(evaluated_siae.siae.id), email.body)
        self.assertIn(evaluated_siae.evaluation_campaign.institution.name, email.body)
        self.assertIn(
            dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, "d E Y"), email.body
        )
        self.assertIn(
            dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, "d E Y"), email.body
        )


class EvaluatedJobApplicationModelTest(TestCase):
    def test_unicity_constraint(self):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        criterion = AdministrativeCriteria.objects.first()

        self.assertTrue(
            EvaluatedAdministrativeCriteria.objects.create(
                evaluated_job_application=evaluated_job_application, administrative_criteria=criterion
            )
        )
        with self.assertRaises(IntegrityError):
            EvaluatedAdministrativeCriteria.objects.create(
                evaluated_job_application=evaluated_job_application, administrative_criteria=criterion
            )

    def test_state(self):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.PENDING, evaluated_job_application.state)
        del evaluated_job_application.state  # clear cached_property stored value

        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof_url=""
        )
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.PROCESSING, evaluated_job_application.state)
        del evaluated_job_application.state

        evaluated_administrative_criteria.proof_url = "https://www.test.com"
        evaluated_administrative_criteria.save(update_fields=["proof_url"])
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.UPLOADED, evaluated_job_application.state)
        del evaluated_job_application.state

        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED, evaluated_job_application.state)
        del evaluated_job_application.state

        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED, evaluated_job_application.state)
        del evaluated_job_application.state

        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.REFUSED, evaluated_job_application.state)
        del evaluated_job_application.state

        evaluated_administrative_criteria.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        )
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2, evaluated_job_application.state)
        del evaluated_job_application.state

        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED, evaluated_job_application.state)

    def test_should_select_criteria_with_mock(self):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        self.assertEqual(
            evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.PENDING,
            evaluated_job_application.should_select_criteria,
        )
        del evaluated_job_application.state

        editable_status = [
            evaluation_enums.EvaluatedJobApplicationsState.PROCESSING,
            evaluation_enums.EvaluatedJobApplicationsState.UPLOADED,
        ]

        for state in editable_status:
            with self.subTest(state=state):
                with mock.patch.object(EvaluatedJobApplication, "state", state):
                    self.assertEqual(
                        evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.EDITABLE,
                        evaluated_job_application.should_select_criteria,
                    )

        not_editable_status = [
            state
            for state in evaluation_enums.EvaluatedJobApplicationsState.choices
            if state != evaluation_enums.EvaluatedJobApplicationsState.PENDING and state not in editable_status
        ]

        for state in not_editable_status:
            with self.subTest(state=state):
                with mock.patch.object(EvaluatedJobApplication, "state", state):
                    self.assertEqual(
                        evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE,
                        evaluated_job_application.should_select_criteria,
                    )

        # REVIEWED
        evaluated_siae = evaluated_job_application.evaluated_siae
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])

        self.assertEqual(
            evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.PENDING,
            evaluated_job_application.should_select_criteria,
        )
        del evaluated_job_application.state

        for state in [
            state
            for state in evaluation_enums.EvaluatedJobApplicationsState.choices
            if state != evaluation_enums.EvaluatedJobApplicationsState.PENDING
        ]:
            with self.subTest(state=state):
                with mock.patch.object(EvaluatedJobApplication, "state", state):
                    self.assertEqual(
                        evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE,
                        evaluated_job_application.should_select_criteria,
                    )

    def test_save_selected_criteria(self):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        criterion1 = AdministrativeCriteria.objects.filter(level=1).first()
        criterion2 = AdministrativeCriteria.objects.filter(level=2).first()

        # nothing to do
        evaluated_job_application.save_selected_criteria(changed_keys=[], cleaned_keys=[])
        self.assertEqual(0, EvaluatedAdministrativeCriteria.objects.count())

        # only create criterion1
        evaluated_job_application.save_selected_criteria(changed_keys=[criterion1.key], cleaned_keys=[criterion1.key])
        self.assertEqual(1, EvaluatedAdministrativeCriteria.objects.count())
        self.assertEqual(
            EvaluatedAdministrativeCriteria.objects.first().administrative_criteria,
            AdministrativeCriteria.objects.filter(level=1).first(),
        )

        # create criterion2 and delete criterion1
        evaluated_job_application.save_selected_criteria(
            changed_keys=[criterion1.key, criterion2.key], cleaned_keys=[criterion2.key]
        )
        self.assertEqual(1, EvaluatedAdministrativeCriteria.objects.count())
        self.assertEqual(
            EvaluatedAdministrativeCriteria.objects.first().administrative_criteria,
            AdministrativeCriteria.objects.filter(level=2).first(),
        )

        # only delete
        evaluated_job_application.save_selected_criteria(changed_keys=[criterion2.key], cleaned_keys=[])
        self.assertEqual(0, EvaluatedAdministrativeCriteria.objects.count())

        # delete non-existant criterion does not raise error ^^
        evaluated_job_application.save_selected_criteria(changed_keys=[criterion2.key], cleaned_keys=[])
        self.assertEqual(0, EvaluatedAdministrativeCriteria.objects.count())

        # atomic : deletion rolled back when trying to create existing criterion
        evaluated_job_application.save_selected_criteria(
            changed_keys=[criterion1.key, criterion2.key], cleaned_keys=[criterion1.key, criterion2.key]
        )
        with self.assertRaises(IntegrityError):
            evaluated_job_application.save_selected_criteria(
                changed_keys=[criterion1.key, criterion2.key], cleaned_keys=[criterion2.key]
            )
        self.assertEqual(2, EvaluatedAdministrativeCriteria.objects.count())


class EvaluatedAdministrativeCriteriaModelTest(TestCase):
    def test_can_upload(self):
        fake_now = timezone.now()

        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=EvaluatedJobApplicationFactory(),
            proof_url="",
        )
        self.assertTrue(evaluated_administrative_criteria.can_upload())

        evaluated_siae = evaluated_administrative_criteria.evaluated_job_application.evaluated_siae
        evaluated_siae.reviewed_at = fake_now
        evaluated_siae.save(update_fields=["reviewed_at"])

        evaluated_administrative_criteria.submitted_at = fake_now
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["submitted_at", "review_state"])
        self.assertTrue(evaluated_administrative_criteria.can_upload())

        for state in [
            state
            for state, _ in evaluation_enums.EvaluatedAdministrativeCriteriaState.choices
            if state != evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        ]:
            with self.subTest(state=state):
                evaluated_administrative_criteria.review_state = state
                evaluated_administrative_criteria.save(update_fields=["review_state"])
                self.assertFalse(evaluated_administrative_criteria.can_upload())
