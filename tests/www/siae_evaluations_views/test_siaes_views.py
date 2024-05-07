import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.messages.test import MessagesTestMixin
from django.core import mail
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils import dateformat, html, timezone
from freezegun import freeze_time

from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria
from itou.utils.templatetags.format_filters import format_approval_number
from tests.companies.factories import CompanyMembershipFactory
from tests.files.factories import FileFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import JobSeekerFactory
from tests.utils.test import BASE_NUM_QUERIES, TestCase


# fixme vincentporte : convert this method into factory
def create_evaluated_siae_with_consistent_datas(siae, user, level_1=True, level_2=False, institution=None):
    job_seeker = JobSeekerFactory()

    eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
        job_seeker,
        author=user,
        author_organization=siae,
        administrative_criteria=list(
            AdministrativeCriteria.objects.filter(
                level__in=[AdministrativeCriteriaLevel.LEVEL_1 if level_1 else None]
                + [AdministrativeCriteriaLevel.LEVEL_2 if level_2 else None]
            )
        ),
    )

    job_application = JobApplicationFactory(
        with_approval=True,
        to_company=siae,
        sender_company=siae,
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
    refused_html = (
        '<span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">Problème constaté</span>'
    )

    def setUp(self):
        super().setUp()
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.siae = membership.company

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
            + 1  # fetch siae membership
            + 1  # fetch evaluated siae
            + 2  # fetch evaluatedjobapplication and its prefetched evaluatedadministrativecriteria
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
            proof=None,
        )
        response = self.client.get(self.url(evaluated_siae))
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
            ),
        )

    def test_redirection_with_submission_freezed_at(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__evaluations_asked_at=timezone.now(),
            siae=self.siae,
            submission_freezed_at=timezone.now(),
        )
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        self.client.force_login(self.user)

        # no criterion selected
        assert (
            evaluated_job_application.should_select_criteria
            == evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE
        )
        response = self.client.get(self.url(evaluated_siae))
        siae_select_criteria_url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        self.assertNotContains(
            response,
            siae_select_criteria_url,
        )
        response = self.client.get(siae_select_criteria_url)
        assert response.status_code == 403

        # at least one criterion selected
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            proof=None,
        )
        assert not evaluated_administrative_criteria.can_upload()
        response = self.client.get(self.url(evaluated_siae))
        siae_upload_doc_url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        self.assertNotContains(
            response,
            siae_upload_doc_url,
        )
        SHOW_PROOF_URL_LABEL = "Voir le justificatif"
        self.assertNotContains(response, SHOW_PROOF_URL_LABEL)
        response = self.client.get(siae_upload_doc_url)
        assert response.status_code == 403

        # If the criteria had a proof, it should be present
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.save(update_fields=("proof",))
        response = self.client.get(self.url(evaluated_siae))
        self.assertContains(response, SHOW_PROOF_URL_LABEL)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:view_proof",
                kwargs={"evaluated_administrative_criteria_id": evaluated_administrative_criteria.pk},
            ),
        )

    @freeze_time("2024-04-08")
    def test_state_hidden_with_submission_freezed_at(self):
        not_in_output = "This string should not be in output."
        evaluated_siae_phase_2bis = EvaluatedSiaeFactory(
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(days=10),
            siae=self.siae,
            submission_freezed_at=timezone.now() - relativedelta(days=1),
            reviewed_at=timezone.now(),
        )
        evaluated_siae_phase_3bis = EvaluatedSiaeFactory(
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(days=10),
            siae=self.siae,
            submission_freezed_at=timezone.now() - relativedelta(days=1),
            reviewed_at=timezone.now() - relativedelta(days=5),
            final_reviewed_at=timezone.now(),
        )
        for evaluated_siae, state, approval_number in [
            (evaluated_siae_phase_2bis, evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED, "XXXXX2412345"),
            (
                evaluated_siae_phase_3bis,
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
                "XXXXX2423456",
            ),
        ]:
            with self.subTest(evaluated_siae):
                evaluated_job_app = EvaluatedJobApplicationFactory(
                    evaluated_siae=evaluated_siae,
                    job_application__job_seeker__first_name="Manny",
                    job_application__job_seeker__last_name="Calavera",
                    job_application__approval__number=approval_number,
                    labor_inspector_explanation=not_in_output,
                )
                EvaluatedAdministrativeCriteriaFactory(
                    evaluated_job_application=evaluated_job_app,
                    uploaded_at=timezone.now() - relativedelta(days=5),
                    submitted_at=timezone.now() - relativedelta(days=3),
                    review_state=state,
                )
                self.client.force_login(self.user)
                response = self.client.get(self.url(evaluated_siae))
                approval_number_html = format_approval_number(approval_number)
                self.assertContains(
                    response,
                    f"""
                    <div class="d-flex flex-column flex-lg-row gap-2 gap-lg-3">
                        <div class="c-box--results__summary flex-grow-1">
                            <i class="ri-pass-valid-line" aria-hidden="true"></i>
                            <div>
                                <h3>PASS IAE {approval_number_html} délivré le 08 Avril 2024</h3>
                                <span>Manny CALAVERA</span>
                            </div>
                        </div>
                        <div>
                            <span class="badge badge-sm rounded-pill text-nowrap bg-success-lighter text-success">
                            Transmis
                            </span>
                        </div>
                    </div>
                    """,
                    html=True,
                    count=1,
                )
                self.assertNotContains(response, not_in_output)
                self.assertNotContains(response, self.refused_html, html=True)

    @freeze_time("2024-04-08")
    def test_application_shown_after_submission_freeze_phase_3bis(self):
        test_data = [
            (
                evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
                "XXXXX2412345",
                '<span class="badge badge-sm rounded-pill text-nowrap bg-success text-white">Validé</span>',
                """
                <strong class="text-success"><i class="ri-check-line"></i> Validé</strong>
                <br>
                <strong class="fs-sm">Bénéficiaire du RSA</strong>
                """,
            ),
            (
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
                "XXXXX2423456",
                self.refused_html,
                """
                <strong class="text-danger"><i class="ri-close-line"></i> Refusé</strong>
                <br>
                <strong class="fs-sm">Bénéficiaire du RSA</strong>
                """,
            ),
        ]
        brsa = AdministrativeCriteria.objects.get(name="Bénéficiaire du RSA")
        for state, approval_number, expected_jobapp_html, expected_criteria_html in test_data:
            with self.subTest(state):
                evaluated_siae_phase_3bis = EvaluatedSiaeFactory(
                    evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(days=10),
                    evaluation_campaign__calendar__adversarial_stage_start=timezone.localdate()
                    - relativedelta(days=5),
                    siae=self.siae,
                    submission_freezed_at=timezone.now() - relativedelta(days=1),
                    reviewed_at=timezone.now() - relativedelta(days=6),
                    final_reviewed_at=timezone.now() - relativedelta(days=6),
                )
                evaluated_job_app = EvaluatedJobApplicationFactory(
                    evaluated_siae=evaluated_siae_phase_3bis,
                    job_application__job_seeker__first_name="Manny",
                    job_application__job_seeker__last_name="Calavera",
                    job_application__approval__number=approval_number,
                )
                EvaluatedAdministrativeCriteriaFactory(
                    evaluated_job_application=evaluated_job_app,
                    administrative_criteria=brsa,
                    uploaded_at=timezone.now() - relativedelta(days=9),
                    submitted_at=timezone.now() - relativedelta(days=8),
                    review_state=state,
                )
                approval_number_html = format_approval_number(approval_number)
                self.client.force_login(self.user)
                response = self.client.get(self.url(evaluated_siae_phase_3bis))
                self.assertContains(
                    response,
                    f"""
                    <div class="d-flex flex-column flex-lg-row gap-2 gap-lg-3">
                        <div class="c-box--results__summary flex-grow-1">
                            <i class="ri-pass-valid-line" aria-hidden="true"></i>
                            <div>
                                <h3>PASS IAE {approval_number_html} délivré le 08 Avril 2024</h3>
                                <span>Manny CALAVERA</span>
                            </div>
                        </div>
                        <div>
                            {expected_jobapp_html}
                        </div>
                    </div>
                    """,
                    html=True,
                    count=1,
                )
                self.assertContains(response, expected_criteria_html, html=True, count=1)

    @freeze_time("2024-04-08")
    def test_state_when_not_sent_before_submission_freeze(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(days=10),
            siae=self.siae,
            submission_freezed_at=timezone.now() - relativedelta(days=1),
        )
        approval_number = "XXXXX2412345"
        EvaluatedJobApplicationFactory(
            evaluated_siae=evaluated_siae,
            job_application__job_seeker__first_name="Manny",
            job_application__job_seeker__last_name="Calavera",
            job_application__approval__number=approval_number,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url(evaluated_siae))
        approval_number_html = format_approval_number(approval_number)
        self.assertContains(
            response,
            f"""
            <div class="d-flex flex-column flex-lg-row gap-2 gap-lg-3">
                <div class="c-box--results__summary flex-grow-1">
                    <i class="ri-pass-valid-line" aria-hidden="true"></i>
                    <div>
                        <h3>PASS IAE {approval_number_html} délivré le 08 Avril 2024</h3>
                        <span>Manny CALAVERA</span>
                    </div>
                </div>
                <div>
                    <span class="badge badge-sm rounded-pill text-nowrap bg-accent-03 text-primary">À traiter</span>
                </div>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_content_with_selected_criteria(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof=None
        )
        self.client.force_login(self.user)

        siae_select_criteria_url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        siae_upload_doc_url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, siae_select_criteria_url)
        self.assertContains(response, html.escape(evaluated_administrative_criteria.administrative_criteria.name))
        self.assertContains(response, siae_upload_doc_url)

        # Freeze submission
        evaluated_job_application.evaluated_siae.evaluation_campaign.freeze(timezone.now())

        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertNotContains(response, siae_select_criteria_url)
        self.assertContains(response, html.escape(evaluated_administrative_criteria.administrative_criteria.name))
        self.assertContains(
            response, '<span class="badge badge-sm rounded-pill text-nowrap bg-info text-white">En cours</span>'
        )
        self.assertNotContains(response, siae_upload_doc_url)

        # Transition to adversarial phase
        evaluated_job_application.evaluated_siae.evaluation_campaign.transition_to_adversarial_phase()
        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, html.escape(evaluated_administrative_criteria.administrative_criteria.name))
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-accent-03 text-primary">À traiter</span>',
        )
        self.assertNotContains(response, siae_select_criteria_url)
        self.assertContains(response, siae_upload_doc_url)

    def test_post_buttons_state(self):
        fake_now = timezone.now()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)

        submit_disabled = """
            <button class="btn btn-primary disabled">
                Soumettre à validation
            </button>
        """
        submit_active = """
            <button class="btn btn-primary">
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
            evaluated_job_application=evaluated_job_application, proof=None
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
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.save(update_fields=["proof"])
        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, submit_active, html=True, count=2)
        self.assertContains(response, select_criteria)
        self.assertContains(response, upload_proof)
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-accent-03 text-primary">
            Justificatifs téléversés
            </span>
            """,
            html=True,
        )

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

    def test_post_buttons_state_with_submission_freezed(self):
        timezone.now()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)

        submit_disabled = """
            <button class="btn btn-primary disabled">
                Soumettre à validation
            </button>
        """
        submit_active = """
            <button class="btn btn-primary">
                Soumettre à validation
            </button>
        """
        select_criteria = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        self.client.force_login(self.user)

        # criterion selected with uploaded proof
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            proof=FileFactory(),
        )
        upload_proof = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )

        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, submit_active, html=True, count=2)
        self.assertContains(response, select_criteria)
        self.assertContains(response, upload_proof)

        # submission freezed
        evaluated_job_application.evaluated_siae.evaluation_campaign.freeze(timezone.now())

        response = self.client.get(self.url(evaluated_job_application.evaluated_siae))
        self.assertContains(response, submit_disabled, html=True, count=1)
        self.assertNotContains(response, submit_active)
        self.assertNotContains(response, select_criteria)
        self.assertNotContains(response, upload_proof)

        # Once the submission has been freezed, you can't reupload it anymore
        response = self.client.get(upload_proof)
        assert response.status_code == 403
        # and you can't change or add criteria
        response = self.client.get(select_criteria)
        assert response.status_code == 403

    def test_shows_labor_inspector_explanation_when_refused(self):
        explanation = "Justificatif invalide au moment de l’embauche."
        evaluated_siae = EvaluatedSiaeFactory(
            siae=self.siae,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(days=50),
            reviewed_at=timezone.now() - relativedelta(days=10),
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(
            evaluated_siae=evaluated_siae, labor_inspector_explanation=explanation
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=15),
            submitted_at=timezone.now() - relativedelta(days=12),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url(evaluated_siae))
        self.assertContains(response, explanation)


class SiaeSelectCriteriaViewTest(TestCase):
    def setUp(self):
        super().setUp()
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.siae = membership.company

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

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
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

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
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

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
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

    def test_post_with_submission_freezed_at(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        # Freeze submission
        evaluated_job_application.evaluated_siae.evaluation_campaign.freeze(timezone.now())

        url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        self.client.force_login(self.user)

        post_data = {criterion.administrative_criteria.key: "on"}
        response = self.client.post(url, data=post_data)
        assert response.status_code == 403
        assert evaluated_job_application.evaluated_administrative_criteria.count() == 0

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
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


@pytest.mark.usefixtures("unittest_compatibility")
class SiaeUploadDocsViewTest(TestCase):
    def setUp(self):
        super().setUp()
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.siae = membership.company

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
        membership = CompanyMembershipFactory()
        user = membership.user
        siae = membership.company
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

        post_data = {"proof": self.pdf_file}
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
        self.pdf_file.seek(0)
        with default_storage.open(evaluated_administrative_criteria.proof_id) as saved_file:
            assert saved_file.read() == self.pdf_file.read()

    def test_post_with_submission_freezed_at(self):
        fake_now = timezone.now()
        self.client.force_login(self.user)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        proof = FileFactory()
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
            uploaded_at=fake_now - relativedelta(days=1),
            proof=proof,
        )
        # Freeze submission
        evaluated_job_application.evaluated_siae.evaluation_campaign.freeze(timezone.now())

        url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )

        post_data = {"proof": self.pdf_file}
        response = self.client.post(url, data=post_data)
        assert response.status_code == 403
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.uploaded_at == fake_now - relativedelta(days=1)
        assert evaluated_administrative_criteria.proof == proof


class SiaeSubmitProofsViewTest(MessagesTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.company = membership.company

    @staticmethod
    def url(evaluated_siae):
        return reverse(
            "siae_evaluations_views:siae_submit_proofs",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

    def test_is_submittable(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.company, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        self.client.force_login(self.user)

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 1  # fetch siae membership
            + 1  # fetch siae infos
            + 3  # fetch evaluatedsiae, evaluatedjobapplication and evaluatedadministrativecriteria
            + 1  # update evaluatedadministrativecriteria
            + 1  # update evaluatedsiae submission_freezed_at
            + 4  # fetch evaluationcampaign, institution, siae and siae members for email notification
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.post(self.url(evaluated_job_application.evaluated_siae))

        assert response.status_code == 302
        assert response.url == reverse("dashboard:index")
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.submitted_at is not None

    def test_is_not_submittable(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.company, self.user)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application, proof=None)
        self.client.force_login(self.user)

        response = self.client.post(self.url(evaluated_job_application.evaluated_siae))
        assert response.status_code == 302
        assert response.url == reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
        )

    def test_is_submittable_with_accepted(self):
        fake_now = timezone.now()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.company, self.user)

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
        not_yet_submitted_job_application = create_evaluated_siae_with_consistent_datas(self.company, self.user)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=not_yet_submitted_job_application,
            proof=FileFactory(),
            submitted_at=None,
        )
        submitted_job_application = EvaluatedJobApplicationFactory(
            job_application=JobApplicationFactory(to_company=self.company),
            evaluated_siae=not_yet_submitted_job_application.evaluated_siae,
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=submitted_job_application,
            proof=FileFactory(),
            submitted_at=fake_now,
        )

        self.client.force_login(self.user)
        response = self.client.post(self.url(submitted_job_application.evaluated_siae))
        assert response.status_code == 302
        assert response.url == "/dashboard/"

    def test_is_not_submittable_with_submission_freezed(self):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.company, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        # Freeze submission
        evaluated_job_application.evaluated_siae.evaluation_campaign.freeze(timezone.now())

        self.client.force_login(self.user)

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 1  # fetch siae membership
            + 1  # fetch siae infos
            + 1  # fetch evaluatedsiae and see that submission is freezed, abort
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.post(self.url(evaluated_job_application.evaluated_siae))

        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
            ),
        )
        self.assertMessages(response, [messages.Message(messages.ERROR, "Impossible de soumettre les documents.")])
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.submitted_at is None

    def test_submitted_email(self):
        institution_membership = InstitutionMembershipFactory()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(
            self.company, self.user, institution=institution_membership.institution
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
            self.company, self.user, institution=institution_membership.institution
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


class SiaeCalendarViewTest(TestCase):
    def setUp(self):
        super().setUp()
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.siae = membership.company

    def test_active_campaign_calendar(self):
        calendar_html = """
            <table class="table">
                <thead class="thead-light">
                    <tr>
                        <th></th>
                        <th scope="col">Dates</th>
                        <th scope="col">Acteurs</th>
                        <th scope="col">Actions attendues</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <th scope="row">Phase 1</th>
                        <td>Du 15 mai 2023 au 11 juin 2023</td>

                        <td>DDETS</td>
                        <td>Sélection du taux de SIAE</td>
                    </tr>
                </tbody>
            </table>
        """
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__calendar__html=calendar_html,
            evaluation_campaign__evaluations_asked_at=timezone.now(),
            siae=self.siae,
        )
        calendar_url = reverse(
            "siae_evaluations_views:campaign_calendar", args=[evaluated_siae.evaluation_campaign.pk]
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, calendar_url)

        response = self.client.get(calendar_url)
        self.assertContains(response, calendar_html)

        # Old campaigns don't have a calendar.
        evaluated_siae.evaluation_campaign.calendar.delete()
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, calendar_url)


class SiaeEvaluatedSiaeDetailViewTest(TestCase):
    def test_access(self):
        membership = CompanyMembershipFactory()
        user = membership.user
        siae = membership.company

        self.client.force_login(user)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(siae, user)
        evaluated_siae = evaluated_job_application.evaluated_siae
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        response = self.client.get(url)
        assert response.status_code == 404

        evaluation_campaign = evaluated_siae.evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(url)
        assert response.status_code == 200


class SiaeEvaluatedJobApplicationViewTest(TestCase):
    refusal_comment_txt = "Commentaire de la DDETS"

    def test_access(self):
        membership = CompanyMembershipFactory()
        user = membership.user
        siae = membership.company

        self.client.force_login(user)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(siae, user)
        evaluated_siae = evaluated_job_application.evaluated_siae
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        url = reverse(
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        response = self.client.get(url)
        assert response.status_code == 404

        evaluation_campaign = evaluated_siae.evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(url)
        self.assertNotContains(response, self.refusal_comment_txt)

        # Refusal comment is only displayed when state is refused
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
            submitted_at=timezone.now(),
        )
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])
        response = self.client.get(url)
        self.assertContains(response, self.refusal_comment_txt)
