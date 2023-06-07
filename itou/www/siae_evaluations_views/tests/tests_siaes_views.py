from dateutil.relativedelta import relativedelta
from django.core import mail
from django.urls import reverse
from django.utils import dateformat, timezone
from freezegun import freeze_time

from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.factories import InstitutionMembershipFactory
from itou.job_applications.factories import JobApplicationFactory
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
from itou.users.factories import JobSeekerFactory
from itou.utils.perms.user import UserInfo
from itou.utils.storage.s3 import S3Upload
from itou.utils.storage.test import S3AccessingTestCase
from itou.utils.test import BASE_NUM_QUERIES, TestCase


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
                level__in=[AdministrativeCriteriaLevel.LEVEL_1 if level_1 else None]
                + [AdministrativeCriteriaLevel.LEVEL_2 if level_2 else None]
            )
        ),
    )

    job_application = JobApplicationFactory(
        with_approval=True,
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


class SiaeJobApplicationListViewTest(S3AccessingTestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae

    @staticmethod
    def url(evaluated_siae):
        return reverse(
            "siae_evaluations_views:siae_job_applications_list", kwargs={"evaluated_siae_pk": evaluated_siae.pk}
        )

    def test_access(self):
        # siae with active campaign
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        self.client.force_login(self.user)
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 1  # verify user is active (middleware)
            + 2  # fetch siae membership and siae infos
            + 1  # fetch evaluated siae
            + 2  # fetch evaluatedjobapplication and its prefetched evaluatedadministrativecriteria
            + 1  # weird fetch siae membership
            # NOTE(vperron): the prefetch is necessary to check the SUBMITTABLE state of the evaluated siae
            # We do those requests "two times" but at least it's now accurate information, and we get
            # the EvaluatedJobApplication list another way so that we can select_related on them.
            + 2  # prefetch evaluated job applications and criteria
            + 1  # Create savepoint (atomic request to update the Django session)
            + 1  # Update the Django session
            + 1  # Release savepoint
        ):
            response = self.client.get(self.url(evaluated_siae))

        assert evaluated_job_application == response.context["evaluated_job_applications"][0]
        assert reverse("dashboard:index") == response.context["back_url"]

        self.assertContains(
            response,
            f"Contrôle initié le "
            f"{dateformat.format(evaluated_siae.evaluation_campaign.evaluations_asked_at, 'd E Y').lower()}",
        )

    def test_redirection(self):
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        self.client.force_login(self.user)

        # no criterion selected
        response = self.client.get(self.url(evaluated_siae))
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
        response = self.client.get(self.url(evaluated_siae))
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
        self.client.force_login(self.user)
        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            ),
        )
        self.assertContains(response, evaluated_administrative_criteria.administrative_criteria.name, html=True)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
            ),
        )

    def test_post_buttons_state(self):
        fake_now = timezone.now()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)

        submit_disabled = """
            <button class="btn btn-outline-primary disabled float-right">
                Soumettre à validation
            </button>
        """
        submit_active = """
            <button class="btn btn-primary float-right">
                Soumettre à validation
            </button>
        """
        select_criteria = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        self.client.force_login(self.user)

        # no criterion selected
        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, submit_disabled, html=True, count=1)
        self.assertContains(response, select_criteria)

        # criterion selected
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof_url=""
        )
        upload_proof = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, submit_disabled, html=True, count=1)
        self.assertContains(response, select_criteria)
        self.assertContains(response, upload_proof)

        # criterion with uploaded proof
        evaluated_administrative_criteria.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria.save(update_fields=["proof_url"])
        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, submit_active, html=True, count=2)
        self.assertContains(response, select_criteria)
        self.assertContains(response, upload_proof)

        # criterion submitted
        evaluated_administrative_criteria.submitted_at = fake_now
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, submit_disabled, html=True, count=1)
        self.assertNotContains(response, select_criteria)
        self.assertNotContains(response, upload_proof)

        # Once the criteria has been submitted, you can't reupload it anymore
        response = self.client.get(upload_proof)
        assert response.status_code == 403
        # and you can't change or add criteria
        response = self.client.get(select_criteria)
        assert response.status_code == 403


class SiaeSelectCriteriaViewTest(TestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae

    def test_access_without_activ_campaign(self):
        self.client.force_login(self.user)

        evaluated_job_application = EvaluatedJobApplicationFactory()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        assert response.status_code == 404

    def test_access_on_ended_campaign(self):
        self.client.force_login(self.user)

        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now()
        )
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        assert response.status_code == 404

    def test_access(self):
        self.client.force_login(self.user)

        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        assert response.status_code == 200

        assert evaluated_job_application.job_application.job_seeker == response.context["job_seeker"]
        assert evaluated_job_application.job_application.approval == response.context["approval"]
        assert (
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
            + f"#{evaluated_job_application.pk}"
            == response.context["back_url"]
        )
        assert evaluated_job_application.compute_state() == response.context["state"]
        assert evaluated_siae.siae.kind == response.context["kind"]

    def test_context_fields_list(self):
        self.client.force_login(self.user)

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
            assert response.status_code == 200
            assert level_1 is bool(response.context["level_1_fields"])
            assert level_2 is bool(response.context["level_2_fields"])

    def test_post(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )

        url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        self.client.force_login(self.user)

        response = self.client.get(url)
        assert response.status_code == 200

        post_data = {criterion.administrative_criteria.key: True}
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        assert 1 == EvaluatedAdministrativeCriteria.objects.count()
        assert (
            criterion.administrative_criteria
            == EvaluatedAdministrativeCriteria.objects.first().administrative_criteria
        )

    def test_initial_data_form(self):
        # no preselected criteria
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        self.client.force_login(self.user)

        response = self.client.get(url)
        assert response.status_code == 200

        for i in range(len(response.context["level_1_fields"])):
            with self.subTest(i):
                assert "checked" not in response.context["level_1_fields"][i].subwidgets[0].data["attrs"]
        for i in range(len(response.context["level_2_fields"])):
            with self.subTest(i):
                assert "checked" not in response.context["level_2_fields"][i].subwidgets[0].data["attrs"]

        # preselected criteria
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
        )

        response = self.client.get(url)
        assert response.status_code == 200

        assert "checked" in response.context["level_1_fields"][0].subwidgets[0].data["attrs"]
        for i in range(1, len(response.context["level_1_fields"])):
            with self.subTest(i):
                assert "checked" not in response.context["level_1_fields"][i].subwidgets[0].data["attrs"]
        for i in range(len(response.context["level_2_fields"])):
            with self.subTest(i):
                assert "checked" not in response.context["level_2_fields"][i].subwidgets[0].data["attrs"]


class SiaeUploadDocsViewTest(S3AccessingTestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae

    def test_access_on_unknown_evaluated_job_application(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": 10000},
            )
        )
        assert response.status_code == 404

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

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
            )
        )
        assert response.status_code == 404

    def test_access_on_ended_campaign(self):
        self.client.force_login(self.user)

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
        assert response.status_code == 404

    @freeze_time("2022-09-14 11:11:11")
    def test_access(self):
        self.maxDiff = None
        self.client.force_login(self.user)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
        )

        s3_upload = S3Upload(kind="evaluations")

        url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = self.client.get(url)
        assert response.status_code == 200

        assert evaluated_administrative_criteria == response.context["evaluated_administrative_criteria"]
        assert (
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
            )
            + f"#{evaluated_job_application.pk}"
            == response.context["back_url"]
        )
        assert evaluated_administrative_criteria == response.context["evaluated_administrative_criteria"]

        for k, v in s3_upload.form_values.items():
            with self.subTest("s3_upload.form_values", k=k):
                assert v == response.context["s3_upload"].form_values[k]

        for k, v in s3_upload.config.items():
            with self.subTest("s3_upload.config", k=k):
                assert v == response.context["s3_upload"].config[k]

    def test_post(self):
        fake_now = timezone.now()
        self.client.force_login(self.user)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
            uploaded_at=fake_now - relativedelta(days=1),
        )
        url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = self.client.get(url)

        # Test fields mandatory to upload to S3
        s3_upload = S3Upload(kind="evaluations")

        # Don't test S3 form fields as it led to flaky tests and
        # it's already done by the Boto library.
        self.assertContains(response, s3_upload.form_values["url"])

        # Config variables
        for _, value in s3_upload.config.items():
            self.assertContains(response, value)

        post_data = {
            "proof_url": "https://server.com/rocky-balboa.pdf",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        next_url = (
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
            )
            + f"#{evaluated_job_application.pk}"
        )
        assert response.url == next_url

        # using already setup test data to control save method of the form
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.submitted_at is None
        assert evaluated_administrative_criteria.uploaded_at > fake_now - relativedelta(days=1)
        assert (
            evaluated_administrative_criteria.review_state
            == evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        )


class SiaeSubmitProofsViewTest(TestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae

    @staticmethod
    def url(evaluated_siae):
        return reverse(
            "siae_evaluations_views:siae_submit_proofs",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

    def test_is_submittable(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        self.client.force_login(self.user)

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 1  # fetch siae membership
            + 2  # fetch siae infos
            + 3  # fetch evaluatedsiae, evaluatedjobapplication and evaluatedadministrativecriteria
            + 1  # update evaluatedadministrativecriteria
            + 4  # fetch evaluationcampaign, institution, siae and siae members for email notification
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.post(self.url(evaluated_job_application.evaluated_siae))

        assert response.status_code == 302
        assert response.url == reverse("dashboard:index")
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.submitted_at is not None

    def test_is_not_submittable(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application, proof_url="")
        self.client.force_login(self.user)

        response = self.client.post(self.url(evaluated_job_application.evaluated_siae))
        assert response.status_code == 302
        assert response.url == reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
        )

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

        self.client.force_login(self.user)
        response = self.client.post(self.url(evaluated_job_application.evaluated_siae))
        assert response.status_code == 302

        evaluated_administrative_criteria0.refresh_from_db()
        assert (
            evaluated_administrative_criteria0.review_state
            == evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        )

        evaluated_administrative_criteria1.refresh_from_db()
        assert (
            evaluated_administrative_criteria1.review_state
            == evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        )
        assert evaluated_administrative_criteria1.submitted_at < evaluated_administrative_criteria0.submitted_at

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

        self.client.force_login(self.user)
        response = self.client.post(self.url(submitted_job_application.evaluated_siae))
        assert response.status_code == 302
        assert response.url == "/dashboard/"

    def test_submitted_email(self):
        institution_membership = InstitutionMembershipFactory()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(
            self.siae, self.user, institution=institution_membership.institution
        )
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application)
        self.client.force_login(self.user)
        response = self.client.post(self.url(evaluated_job_application.evaluated_siae))
        assert response.status_code == 302

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert (
            f"[Contrôle a posteriori] La structure { evaluated_job_application.evaluated_siae.siae.kind } "
            f"{ evaluated_job_application.evaluated_siae.siae.name } a transmis ses pièces justificatives."
        ) == email.subject
        assert (
            f"La structure { evaluated_job_application.evaluated_siae.siae.kind } "
            f"{ evaluated_job_application.evaluated_siae.siae.name } vient de vous transmettre ses pièces"
        ) in email.body
        assert (
            email.to[0]
            == evaluated_job_application.evaluated_siae.evaluation_campaign.institution.active_members.first().email
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

        self.client.force_login(self.user)
        response = self.client.post(self.url(evaluated_job_application.evaluated_siae))

        assert response.status_code == 404
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.submitted_at is None
