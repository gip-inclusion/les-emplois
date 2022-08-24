from dateutil.relativedelta import relativedelta
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import dateformat, timezone

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.factories import InstitutionMembershipFactory
from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria
from itou.siaes.factories import SiaeMembershipFactory
from itou.users.enums import KIND_SIAE_STAFF
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from itou.utils.perms.user import UserInfo
from itou.utils.storage.s3 import S3Upload


# fixme vincentporte : convert this method into factory
def create_evaluated_siae_with_consistent_datas(siae, user, level_1=True, level_2=False, institution=None):
    job_seeker = JobSeekerFactory()

    user_info = UserInfo(
        user=user, kind=KIND_SIAE_STAFF, siae=siae, prescriber_organization=None, is_authorized_prescriber=False
    )

    eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
        job_seeker,
        user_info,
        administrative_criteria=list(
            AdministrativeCriteria.objects.filter(
                level__in=[AdministrativeCriteria.Level.LEVEL_1 if level_1 else None]
                + [AdministrativeCriteria.Level.LEVEL_2 if level_2 else None]
            )
        ),
    )

    job_application = JobApplicationWithApprovalFactory(
        to_siae=siae,
        sender_siae=siae,
        eligibility_diagnosis=eligibility_diagnosis,
        hiring_start_at=timezone.now() - relativedelta(months=2),
    )

    if institution:
        evaluation_campaign = EvaluationCampaignFactory(institution=institution, evaluations_asked_at=timezone.now())
    else:
        evaluation_campaign = EvaluationCampaignFactory(evaluations_asked_at=timezone.now())

    evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign, siae=siae)
    evaluated_job_application = EvaluatedJobApplicationFactory(
        job_application=job_application, evaluated_siae=evaluated_siae
    )

    return evaluated_job_application


class SiaeJobApplicationListViewTest(TestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae
        self.url = reverse("siae_evaluations_views:siae_job_applications_list")

    def test_access(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        # siae without active campaign
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["evaluations_asked_at"])
        self.assertFalse(response.context["evaluated_job_applications"])
        self.assertFalse(response.context["is_submittable"])
        self.assertContains(response, "Vous n'avez aucun contrôle en cours.")

        # siae with active campaign
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        with self.assertNumQueries(
            1  # fetch django session
            + 1  # fetch user
            + 2  # fetch siae membership and siae infos
            + 1  # fetch evaluated siae
            + 2  # fetch evaluatedjobapplication and its prefetched evaluatedadministrativecriteria
            + 1  # aggregate min evaluation_campaign notification date
            + 2  # weird fetch siae membership and social account
            # NOTE(vperron): the prefecth is necessary to check the SUBMITTABLE state of the evaluated siae
            # We do those requests "two times" but at least it's now accurate information, and we get
            # the EvaluatedJobApplication list another way so that we can select_related on them.
            + 2  # prefetch evaluated job applications and criteria
        ):
            response = self.client.get(self.url)

        self.assertEqual(
            evaluated_siae.evaluation_campaign.evaluations_asked_at, response.context["evaluations_asked_at"]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            evaluated_job_application,
            response.context["evaluated_job_applications"][0],
        )
        self.assertEqual(
            reverse("dashboard:index"),
            response.context["back_url"],
        )

        self.assertContains(
            response,
            f"Contrôle initié le "
            f"{dateformat.format(evaluated_siae.evaluation_campaign.evaluations_asked_at, 'd E Y').lower()}",
        )

    def test_redirection(self):
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        # no criterion selected
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            ),
        )

        # at least one criterion selected
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            proof_url="",
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
            ),
        )

    def test_content_with_selected_criteria(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof_url=""
        )
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            ),
        )
        self.assertContains(response, evaluated_administrative_criteria.administrative_criteria.name)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
            ),
        )

    def test_links_mechanism(self):
        fake_now = timezone.now()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)

        submit_disabled = (
            '<a class="btn btn-outline-primary disabled float-right" href="'
            + reverse("siae_evaluations_views:siae_submit_proofs")
            + '">'
        )
        submit_active = (
            '<a class="btn btn-primary float-right" href="'
            + reverse("siae_evaluations_views:siae_submit_proofs")
            + '">'
        )
        select_criteria = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        # no criterion selected
        response = self.client.get(self.url)
        self.assertContains(response, submit_disabled)
        self.assertContains(response, select_criteria)

        # criterion selected
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof_url=""
        )
        upload_proof = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = self.client.get(self.url)
        self.assertContains(response, submit_disabled)
        self.assertContains(response, select_criteria)
        self.assertContains(response, upload_proof)

        # criterion with uploaded proof
        evaluated_administrative_criteria.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria.save(update_fields=["proof_url"])
        response = self.client.get(self.url)
        self.assertContains(response, submit_active)
        self.assertContains(response, select_criteria)
        self.assertContains(response, upload_proof)

        # criterion submitted
        evaluated_administrative_criteria.submitted_at = fake_now
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        response = self.client.get(self.url)
        self.assertContains(response, submit_disabled)
        self.assertNotContains(response, select_criteria)
        self.assertNotContains(response, upload_proof)


class SiaeSelectCriteriaViewTest(TestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae

    def test_access_without_activ_campaign(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        evaluated_job_application = EvaluatedJobApplicationFactory()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_access_on_ended_campaign(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now()
        )
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_access(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            evaluated_job_application.job_application.job_seeker,
            response.context["job_seeker"],
        )
        self.assertEqual(
            evaluated_job_application.job_application.approval,
            response.context["approval"],
        )
        self.assertEqual(
            reverse("siae_evaluations_views:siae_job_applications_list") + f"#{evaluated_job_application.pk}",
            response.context["back_url"],
        )
        self.assertEqual(
            evaluated_job_application.state,
            response.context["state"],
        )
        self.assertEqual(
            evaluated_siae.siae.kind,
            response.context["kind"],
        )

    def test_context_fields_list(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        # Combinations :
        # (True, False) = eligibility diagnosis with level 1 administrative criteria
        # (False, True) = eligibility diagnosis with level 2 administrative criteria
        # (True, True) = eligibility diagnosis with level 1 and level 2 administrative criteria
        # (False, False) = eligibility diagnosis ~without~ administrative criteria

        for level_1, level_2 in [(True, False), (False, True), (True, True), (False, False)]:
            with self.subTest(level_1=level_1, level_2=level_2):
                evaluated_job_application = create_evaluated_siae_with_consistent_datas(
                    self.siae, self.user, level_1=level_1, level_2=level_2
                )
            response = self.client.get(
                reverse(
                    "siae_evaluations_views:siae_select_criteria",
                    kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
                )
            )
            self.assertEqual(response.status_code, 200)
            self.assertIs(level_1, bool(response.context["level_1_fields"]))
            self.assertIs(level_2, bool(response.context["level_2_fields"]))

    def test_post(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )

        url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {criterion.administrative_criteria.key: True}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(1, EvaluatedAdministrativeCriteria.objects.count())
        self.assertEqual(
            criterion.administrative_criteria,
            EvaluatedAdministrativeCriteria.objects.first().administrative_criteria,
        )

    def test_initial_data_form(self):

        # no preselected criteria
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        for i in range(len(response.context["level_1_fields"])):
            with self.subTest(i):
                self.assertNotIn("checked", response.context["level_1_fields"][i].subwidgets[0].data["attrs"])
        for i in range(len(response.context["level_2_fields"])):
            with self.subTest(i):
                self.assertNotIn("checked", response.context["level_2_fields"][i].subwidgets[0].data["attrs"])

        # preselected criteria
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
        )

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.assertIn("checked", response.context["level_1_fields"][0].subwidgets[0].data["attrs"])
        for i in range(1, len(response.context["level_1_fields"])):
            with self.subTest(i):
                self.assertNotIn("checked", response.context["level_1_fields"][i].subwidgets[0].data["attrs"])
        for i in range(len(response.context["level_2_fields"])):
            with self.subTest(i):
                self.assertNotIn("checked", response.context["level_2_fields"][i].subwidgets[0].data["attrs"])


class SiaeUploadDocsViewTest(TestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae

    def test_access_on_unknown_evaluated_job_application(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": 10000},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_access_without_ownership(self):
        membership = SiaeMembershipFactory()
        user = membership.user
        siae = membership.siae
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(siae, user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
        )

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_access_on_ended_campaign(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        evaluation_campaign = evaluated_job_application.evaluated_siae.evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])

        url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_access(self):
        self.maxDiff = None
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
        )

        s3_upload = S3Upload(kind="evaluations")
        s3_form_values = s3_upload.form_values
        s3_upload_config = s3_upload.config

        url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            evaluated_administrative_criteria,
            response.context["evaluated_administrative_criteria"],
        )
        self.assertEqual(
            reverse("siae_evaluations_views:siae_job_applications_list") + f"#{evaluated_job_application.pk}",
            response.context["back_url"],
        )
        self.assertEqual(evaluated_administrative_criteria, response.context["evaluated_administrative_criteria"])

        for k, v in s3_form_values.items():
            with self.subTest("s3_form_values", k=k):
                self.assertEqual(v, response.context["s3_form_values"][k])

        for k, v in s3_upload_config.items():
            with self.subTest("s3_upload_config", k=k):
                self.assertEqual(v, response.context["s3_upload_config"][k])

    def test_post(self):
        fake_now = timezone.now()
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
            submitted_at=fake_now - relativedelta(days=1),
            uploaded_at=fake_now - relativedelta(days=1),
        )
        url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Test fields mandatory to upload to S3
        s3_upload = S3Upload(kind="evaluations")
        s3_upload_config = s3_upload.config
        s3_form_endpoint = s3_upload.form_values["url"]

        # Don't test S3 form fields as it led to flaky tests and
        # it's already done by the Boto library.
        self.assertContains(response, s3_form_endpoint)

        # Config variables
        for _, value in s3_upload_config.items():
            self.assertContains(response, value)

        post_data = {
            "proof_url": "https://server.com/rocky-balboa.pdf",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("siae_evaluations_views:siae_job_applications_list") + f"#{evaluated_job_application.pk}"
        self.assertEqual(response.url, next_url)

        # using already setup test data to control save method of the form
        evaluated_administrative_criteria.refresh_from_db()
        self.assertIsNone(evaluated_administrative_criteria.submitted_at)
        self.assertGreater(evaluated_administrative_criteria.uploaded_at, fake_now - relativedelta(days=1))
        self.assertEqual(
            evaluated_administrative_criteria.review_state,
            evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
        )


class SiaeSubmitProofsViewTest(TestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae
        self.url = reverse("siae_evaluations_views:siae_submit_proofs")

    def test_is_submittable(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        with self.assertNumQueries(
            1  # fetch django session
            + 1  # fetch user
            + 1  # fetch siae membership
            + 2  # fetch siae infos
            + 3  # fetch evaluatedsiae, evaluatedjobapplication and evaluatedadministrativecriteria
            + 1  # update evaluatedadministrativecriteria
            + 4  # fetch evaluationcampaign, institution, siae and siae members for email notification
            + 3  # savepoint, update session, release savepoint
        ):

            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))
        evaluated_administrative_criteria.refresh_from_db()
        self.assertNotEqual(evaluated_administrative_criteria.submitted_at, None)

    def test_is_not_submittable(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application, proof_url="")
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("siae_evaluations_views:siae_job_applications_list"))

    def test_is_submittable_with_accepted(self):
        fake_now = timezone.now()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)

        evaluated_administrative_criteria0 = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        evaluated_administrative_criteria1 = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
            submitted_at=fake_now - relativedelta(days=1),
        )

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        evaluated_administrative_criteria0.refresh_from_db()
        self.assertEqual(
            evaluated_administrative_criteria0.review_state,
            evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
        )

        evaluated_administrative_criteria1.refresh_from_db()
        self.assertEqual(
            evaluated_administrative_criteria1.review_state,
            evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        self.assertLess(
            evaluated_administrative_criteria1.submitted_at, evaluated_administrative_criteria0.submitted_at
        )

    def test_is_submittable_with_a_forgotten_submitted_doc(self):
        fake_now = timezone.now()
        not_yet_submitted_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=not_yet_submitted_job_application,
            proof_url="http://something.com/good",
            submitted_at=None,
        )
        submitted_job_application = EvaluatedJobApplicationFactory(
            job_application=JobApplicationFactory(to_siae=self.siae),
            evaluated_siae=not_yet_submitted_job_application.evaluated_siae,
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=submitted_job_application,
            proof_url="http://something.com/other_good",
            submitted_at=fake_now,
        )

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")

    def test_submitted_email(self):
        institution_membership = InstitutionMembershipFactory()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(
            self.siae, self.user, institution=institution_membership.institution
        )
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application)
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(
            (
                f"[Contrôle a posteriori] La structure { evaluated_job_application.evaluated_siae.siae.kind } "
                f"{ evaluated_job_application.evaluated_siae.siae.name } a transmis ses pièces justificatives."
            ),
            email.subject,
        )
        self.assertIn(
            (
                f"La structure { evaluated_job_application.evaluated_siae.siae.kind } "
                f"{ evaluated_job_application.evaluated_siae.siae.name } vient de vous transmettre ses pièces"
            ),
            email.body,
        )
        self.assertEqual(
            email.to[0],
            evaluated_job_application.evaluated_siae.evaluation_campaign.institution.active_members.first(),
        )

    def test_campaign_is_ended(self):
        # fixme vincentporte : convert data preparation into factory
        institution_membership = InstitutionMembershipFactory()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(
            self.siae, self.user, institution=institution_membership.institution
        )
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        evaluation_campaign = evaluated_job_application.evaluated_siae.evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        evaluated_administrative_criteria.refresh_from_db()
        self.assertEqual(evaluated_administrative_criteria.submitted_at, None)
