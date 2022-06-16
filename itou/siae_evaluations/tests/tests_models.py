from dateutil.relativedelta import relativedelta
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import dateformat, timezone

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.factories import InstitutionFactory, InstitutionWith2MembershipFactory
from itou.institutions.models import Institution
from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication, JobApplicationQuerySet, JobApplicationWorkflow
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.factories import (
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
from itou.siaes.factories import SiaeFactory, SiaeWith2MembershipsFactory, SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory
from itou.utils.perms.user import KIND_SIAE_STAFF, UserInfo


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

        # zero job application
        qs = select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae))
        self.assertIsInstance(qs, JobApplicationQuerySet)
        self.assertEqual(0, qs.count())

        # one job applications made by SIAE
        job_application = JobApplicationFactory(to_siae=siae)
        self.assertEqual(
            job_application,
            select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).first(),
        )
        self.assertEqual(1, select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count())

        # from 2 job applications to 10
        for i in range(1, 10):
            with self.subTest(i):
                JobApplicationFactory(to_siae=siae)
                self.assertEqual(
                    evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN,
                    select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count(),
                )

        self.assertEqual(10, JobApplication.objects.filter(to_siae=siae).count())

        # from 20 job applications to 100
        for i in range(10, 100, 10):
            with self.subTest(i):
                JobApplicationFactory.create_batch(10, to_siae=siae)
                self.assertEqual(
                    int(
                        JobApplication.objects.filter(to_siae=siae).count()
                        * evaluation_enums.EvaluationJobApplicationsBoundariesNumber.SELECTION_PERCENTAGE
                        / 100
                    ),
                    select_min_max_job_applications(JobApplication.objects.filter(to_siae=siae)).count(),
                )

        self.assertEqual(100, JobApplication.objects.filter(to_siae=siae).count())

        # more 100 job applications
        for i in range(100, 200, 50):
            with self.subTest(i):
                JobApplicationFactory.create_batch(50, to_siae=siae)
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
                InstitutionFactory(kind=kind)
                self.assertEqual(
                    0, create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at)
                )
                self.assertEqual(0, EvaluationCampaign.objects.all().count())
                self.assertEqual(len(mail.outbox), 0)

        # institution DDETS
        InstitutionWith2MembershipFactory.create_batch(2, kind=Institution.Kind.DDETS)
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
        for kind in [k for (k, _) in SiaeKind.choices if k not in evaluation_enums.EvaluationSiaesKind.Evaluable]:
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
        siae = SiaeWithMembershipFactory(department=evaluation_campaign.institution.department)
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
            with self.subTest(evaluated_job_application=evaluated_job_application):
                self.assertEqual(evaluated_siae, evaluated_job_application.evaluated_siae)

        # retry on populated campaign
        with self.assertRaises(CampaignAlreadyPopulatedException):
            evaluation_campaign.populate(fake_now)


class EvaluationCampaignEmailMethodsTest(TestCase):
    def test_get_email_institution_notification(self):
        institution = InstitutionWith2MembershipFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution)

        date = timezone.now().date()
        email = evaluation_campaign.get_email_institution_notification(date)

        self.assertEqual(email.to, list(institution.active_members))
        self.assertIn(reverse("dashboard:index"), email.body)
        self.assertIn(
            f"Le choix du taux de SIAE à contrôler est possible jusqu’au {dateformat.format(date, 'd E Y')}",
            email.body,
        )
        self.assertIn(f"avant le {dateformat.format(date, 'd E Y')}", email.subject)

    def test_get_email_eligible_siae(self):
        siae = SiaeWith2MembershipsFactory()
        evaluated_siae = EvaluatedSiaeFactory(siae=siae)
        email = evaluated_siae.get_email_eligible_siae()

        self.assertEqual(email.to, list(evaluated_siae.siae.active_admin_members))
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

    def test_get_email_institution_opening_siae(self):
        institution = InstitutionWith2MembershipFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution)

        email = evaluation_campaign.get_email_institution_opening_siae()
        self.assertEqual(email.to, list(institution.active_members))
        self.assertIn(dateformat.format(timezone.now() + relativedelta(weeks=6), "d E Y"), email.body)
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
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__ended_at=fake_now)

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
        criteria = AdministrativeCriteria.objects.first()
        evaluated_administrative_criteria0 = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application, administrative_criteria=criteria
        )
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.PENDING, evaluated_siae.state)
        del evaluated_siae.state

        # with proof_url
        evaluated_administrative_criteria0.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria0.save(update_fields=["proof_url"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTABLE, evaluated_siae.state)
        del evaluated_siae.state

        # with submitted_at
        evaluated_administrative_criteria0.submitted_at = fake_now
        evaluated_administrative_criteria0.save(update_fields=["submitted_at"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.SUBMITTED, evaluated_siae.state)
        del evaluated_siae.state

        # with review_state REFUSED
        evaluated_administrative_criteria0.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.REFUSED, evaluated_siae.state)
        del evaluated_siae.state

        # with review_state ACCEPTED
        evaluated_administrative_criteria0.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        )
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ACCEPTED, evaluated_siae.state)
        del evaluated_siae.state

        # ADVERSARIAL_STAGE : REVIEWED with review_state REFUSED
        evaluated_administrative_criteria0.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = fake_now
        evaluated_siae.save(update_fields=["reviewed_at"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE, evaluated_siae.state)
        del evaluated_siae.state

        # REVIEWED with review_state ACCEPTED
        evaluated_administrative_criteria0.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        )
        evaluated_administrative_criteria0.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = fake_now
        evaluated_siae.save(update_fields=["reviewed_at"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.REVIEWED, evaluated_siae.state)

    def test_state_integration(self):
        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__ended_at=fake_now)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        criteria = AdministrativeCriteria.objects.all()[:3]

        evaluated_administrative_criteria = []
        for i in range(3):
            evaluated_administrative_criteria.append(
                EvaluatedAdministrativeCriteria.objects.create(
                    evaluated_job_application=evaluated_job_application,
                    administrative_criteria=criteria[i],
                    proof_url="https://server.com/rocky-balboa.pdf",
                    submitted_at=fake_now,
                )
            )

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
        evaluated_administrative_criteria[
            0
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[0].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.REFUSED, evaluated_siae.state)
        del evaluated_siae.state

        # three Accepted
        evaluated_administrative_criteria[
            1
        ].review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria[1].save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedSiaeState.ACCEPTED, evaluated_siae.state)
        del evaluated_siae.state

    def test_review(self):
        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__ended_at=fake_now)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        criteria = AdministrativeCriteria.objects.first()
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application, administrative_criteria=criteria
        )
        evaluated_administrative_criteria.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria.submitted_at = fake_now
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["proof_url", "submitted_at", "review_state"])

        evaluated_siae.review()
        evaluated_siae.refresh_from_db()
        self.assertIsNotNone(evaluated_siae.reviewed_at)

        evaluated_siae.reviewed_at = None
        evaluated_siae.save(update_fields=["reviewed_at"])

        evaluated_siae.review()
        evaluated_siae.refresh_from_db()
        self.assertIsNotNone(evaluated_siae.reviewed_at)


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

        criterion = AdministrativeCriteria.objects.first()
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application, administrative_criteria=criterion
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

        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        self.assertEqual(evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED, evaluated_job_application.state)

    def test_should_select_criteria(self):
        evaluated_job_application = EvaluatedJobApplicationFactory()
        self.assertEqual(
            evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.PENDING,
            evaluated_job_application.should_select_criteria,
        )
        del evaluated_job_application.state
        del evaluated_job_application.should_select_criteria

        criterion = AdministrativeCriteria.objects.first()
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application, administrative_criteria=criterion
        )
        self.assertEqual(
            evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.EDITABLE,
            evaluated_job_application.should_select_criteria,
        )
        del evaluated_job_application.state
        del evaluated_job_application.should_select_criteria

        evaluated_administrative_criteria.proof_url = "https://www.test.com"
        evaluated_administrative_criteria.save(update_fields=["proof_url"])
        self.assertEqual(
            evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.EDITABLE,
            evaluated_job_application.should_select_criteria,
        )
        del evaluated_job_application.state
        del evaluated_job_application.should_select_criteria

        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
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
