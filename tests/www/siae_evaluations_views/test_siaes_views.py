import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.core import mail
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils import dateformat, html, timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertNumQueries, assertRedirects

from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria
from itou.utils.templatetags.format_filters import format_approval_number
from tests.companies.factories import CompanyMembershipFactory
from tests.files.factories import FileFactory
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import JobSeekerFactory
from tests.utils.test import BASE_NUM_QUERIES


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


SIAE_JOB_APPLICATION_LIST_REFUSED_HTML = (
    '<span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">Problème constaté</span>'
)


class TestSiaeJobApplicationListView:
    def setup_method(self):
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.siae = membership.company

    @staticmethod
    def url(evaluated_siae):
        return reverse(
            "siae_evaluations_views:siae_job_applications_list", kwargs={"evaluated_siae_pk": evaluated_siae.pk}
        )

    def test_access(self, client):
        # siae with active campaign
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        client.force_login(self.user)
        # 1.  SELECT django_session
        # 2.  SELECT users_user
        # 3.  SELECT companies_companymembership
        # 4.  SELECT companies_company
        # END of middleware
        # 5.  SAVEPOINT
        # 6.  SELECT siae_evaluations_evaluatedsiae
        # 7.  SELECT siae_evaluations_evaluatedjobapplication
        # 8.  SELECT siae_evaluations_evaluatedadministrativecriteria
        # 9.  SELECT companies_siaeconvention (menu checks for financial annexes)
        # 10. SELECT users_user (menu checks for active admin)
        # NOTE(vperron): the prefetch is necessary to check the SUBMITTABLE state of the evaluated siae
        # We do those requests "two times" but at least it's now accurate information, and we get
        # the EvaluatedJobApplication list another way so that we can select_related on them.
        # 11. SELECT siae_evaluations_evaluatedjobapplication
        # 12. SELECT siae_evaluations_evaluatedadministrativecriteria (prefetch)
        # 13. RELEASE SAVEPOINT
        # 14. SAVEPOINT
        # 15. UPDATE django_session
        # 16. RELEASE SAVEPOINT
        with assertNumQueries(16):
            response = client.get(self.url(evaluated_siae))

        assert evaluated_job_application == response.context["evaluated_job_applications"][0]
        assert reverse("dashboard:index") == response.context["back_url"]

        assertContains(
            response,
            f"Contrôle initié le "
            f"{dateformat.format(evaluated_siae.evaluation_campaign.evaluations_asked_at, 'd E Y').lower()}",
        )

    def test_redirection(self, client):
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        client.force_login(self.user)

        # no criterion selected
        response = client.get(self.url(evaluated_siae))
        assertContains(
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
        response = client.get(self.url(evaluated_siae))
        assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
            ),
        )

    def test_redirection_with_submission_freezed_at(self, client):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__evaluations_asked_at=timezone.now(),
            siae=self.siae,
            submission_freezed_at=timezone.now(),
        )
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        client.force_login(self.user)

        # no criterion selected
        assert (
            evaluated_job_application.should_select_criteria
            == evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE
        )
        response = client.get(self.url(evaluated_siae))
        siae_select_criteria_url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        assertNotContains(
            response,
            siae_select_criteria_url,
        )
        response = client.get(siae_select_criteria_url)
        assert response.status_code == 403

        # at least one criterion selected
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            proof=None,
        )
        assert not evaluated_administrative_criteria.can_upload()
        response = client.get(self.url(evaluated_siae))
        siae_upload_doc_url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        assertNotContains(
            response,
            siae_upload_doc_url,
        )
        SHOW_PROOF_URL_LABEL = "Voir le justificatif"
        assertNotContains(response, SHOW_PROOF_URL_LABEL)
        response = client.get(siae_upload_doc_url)
        assert response.status_code == 403

        # If the criteria had a proof, it should be present
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.save(update_fields=("proof",))
        response = client.get(self.url(evaluated_siae))
        assertContains(response, SHOW_PROOF_URL_LABEL)
        assertContains(
            response,
            reverse(
                "siae_evaluations_views:view_proof",
                kwargs={"evaluated_administrative_criteria_id": evaluated_administrative_criteria.pk},
            ),
        )

    @pytest.mark.parametrize(
        "evaluated_siae_kwargs,state,approval_number",
        [
            [
                {"reviewed_at": timezone.now()},
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
                "XXXXX2412345",
            ],
            [
                {"reviewed_at": timezone.now() - relativedelta(days=5), "final_reviewed_at": timezone.now()},
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
                "XXXXX2423456",
            ],
        ],
    )
    @freeze_time("2024-04-08")
    def test_state_hidden_with_submission_freezed_at(self, client, evaluated_siae_kwargs, state, approval_number):
        institution = InstitutionFactory(name="DDETS 01", department="01")
        not_in_output = "This string should not be in output."
        evaluated_siae = EvaluatedSiaeFactory(
            submission_freezed_at=timezone.now() - relativedelta(days=1),
            siae=self.siae,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(days=10),
            evaluation_campaign__institution=institution,
            **evaluated_siae_kwargs,
        )
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
        client.force_login(self.user)
        response = client.get(self.url(evaluated_siae))
        approval_number_html = format_approval_number(approval_number)
        assertContains(
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
        assertNotContains(response, not_in_output)
        assertNotContains(response, SIAE_JOB_APPLICATION_LIST_REFUSED_HTML, html=True)

    @freeze_time("2024-04-08")
    @pytest.mark.parametrize(
        "state,approval_number,expected_jobapp_html,expected_criteria_html",
        [
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
                SIAE_JOB_APPLICATION_LIST_REFUSED_HTML,
                """
                <strong class="text-danger"><i class="ri-close-line"></i> Refusé</strong>
                <br>
                <strong class="fs-sm">Bénéficiaire du RSA</strong>
                """,
            ),
        ],
    )
    def test_application_shown_after_submission_freeze_phase_3bis(
        self, client, state, approval_number, expected_jobapp_html, expected_criteria_html
    ):
        institution = InstitutionFactory(name="DDETS 01", department="01")
        brsa = AdministrativeCriteria.objects.get(name="Bénéficiaire du RSA")
        evaluated_siae_phase_3bis = EvaluatedSiaeFactory(
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(days=10),
            evaluation_campaign__calendar__adversarial_stage_start=timezone.localdate() - relativedelta(days=5),
            evaluation_campaign__institution=institution,
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
        client.force_login(self.user)
        response = client.get(self.url(evaluated_siae_phase_3bis))
        assertContains(
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
        assertContains(response, expected_criteria_html, html=True, count=1)

    @freeze_time("2024-04-08")
    def test_state_when_not_sent_before_submission_freeze(self, client):
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
        client.force_login(self.user)
        response = client.get(self.url(evaluated_siae))
        approval_number_html = format_approval_number(approval_number)
        assertContains(
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

    def test_content_with_selected_criteria(self, client):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof=None
        )
        client.force_login(self.user)

        siae_select_criteria_url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        siae_upload_doc_url = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertContains(response, siae_select_criteria_url)
        assertContains(response, html.escape(evaluated_administrative_criteria.administrative_criteria.name))
        assertContains(response, siae_upload_doc_url)

        # Freeze submission
        evaluated_job_application.evaluated_siae.evaluation_campaign.freeze(timezone.now())

        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertNotContains(response, siae_select_criteria_url)
        assertContains(response, html.escape(evaluated_administrative_criteria.administrative_criteria.name))
        assertContains(
            response, '<span class="badge badge-sm rounded-pill text-nowrap bg-info text-white">En cours</span>'
        )
        assertNotContains(response, siae_upload_doc_url)

        # Transition to adversarial phase
        evaluated_job_application.evaluated_siae.evaluation_campaign.transition_to_adversarial_phase()
        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertContains(response, html.escape(evaluated_administrative_criteria.administrative_criteria.name))
        assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-accent-03 text-primary">À traiter</span>',
        )
        assertNotContains(response, siae_select_criteria_url)
        assertContains(response, siae_upload_doc_url)

    def test_post_buttons_state(self, client):
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

        client.force_login(self.user)

        # no criterion selected
        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertContains(response, submit_disabled, html=True, count=1)
        assertContains(response, select_criteria)

        # criterion selected
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application, proof=None
        )
        upload_proof = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )
        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertContains(response, submit_disabled, html=True, count=1)
        assertContains(response, select_criteria)
        assertContains(response, upload_proof)

        # criterion with uploaded proof
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.save(update_fields=["proof"])
        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertContains(response, submit_active, html=True, count=2)
        assertContains(response, select_criteria)
        assertContains(response, upload_proof)
        assertContains(
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
        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertContains(response, submit_disabled, html=True, count=1)
        assertNotContains(response, select_criteria)
        assertNotContains(response, upload_proof)

        # Once the criteria has been submitted, you can't reupload it anymore
        response = client.get(upload_proof)
        assert response.status_code == 403
        # and you can't change or add criteria
        response = client.get(select_criteria)
        assert response.status_code == 403

    def test_post_buttons_state_with_submission_freezed(self, client):
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

        client.force_login(self.user)

        # criterion selected with uploaded proof
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            proof=FileFactory(),
        )
        upload_proof = reverse(
            "siae_evaluations_views:siae_upload_doc",
            kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
        )

        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertContains(response, submit_active, html=True, count=2)
        assertContains(response, select_criteria)
        assertContains(response, upload_proof)

        # submission freezed
        evaluated_job_application.evaluated_siae.evaluation_campaign.freeze(timezone.now())

        response = client.get(self.url(evaluated_job_application.evaluated_siae))
        assertContains(response, submit_disabled, html=True, count=1)
        assertNotContains(response, submit_active)
        assertNotContains(response, select_criteria)
        assertNotContains(response, upload_proof)

        # Once the submission has been freezed, you can't reupload it anymore
        response = client.get(upload_proof)
        assert response.status_code == 403
        # and you can't change or add criteria
        response = client.get(select_criteria)
        assert response.status_code == 403

    def test_shows_labor_inspector_explanation_when_refused(self, client):
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
        client.force_login(self.user)
        response = client.get(self.url(evaluated_siae))
        assertContains(response, explanation)


class TestSiaeSelectCriteriaView:
    def setup_method(self):
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.siae = membership.company

    def test_access_without_activ_campaign(self, client):
        client.force_login(self.user)

        evaluated_job_application = EvaluatedJobApplicationFactory()
        response = client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        assert response.status_code == 404

    def test_access_on_ended_campaign(self, client):
        client.force_login(self.user)

        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now()
        )
        response = client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        assert response.status_code == 404

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
    def test_access(self, client):
        client.force_login(self.user)

        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        response = client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )

        assert response.status_code == 200

        assert (
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
            + f"#{evaluated_job_application.pk}"
            == response.context["back_url"]
        )
        assert evaluated_siae.siae.kind == response.context["kind"]

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
    @pytest.mark.parametrize("level_1,level_2", [(True, False), (False, True), (True, True), (False, False)])
    def test_context_fields_list(self, client, level_1, level_2):
        institution = InstitutionFactory(name="DDETS 01", department="01")
        client.force_login(self.user)

        # Combinations :
        # (True, False) = eligibility diagnosis with level 1 administrative criteria
        # (False, True) = eligibility diagnosis with level 2 administrative criteria
        # (True, True) = eligibility diagnosis with level 1 and level 2 administrative criteria
        # (False, False) = eligibility diagnosis ~without~ administrative criteria

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(
            self.siae,
            self.user,
            level_1=level_1,
            level_2=level_2,
            institution=institution,
        )
        response = client.get(
            reverse(
                "siae_evaluations_views:siae_select_criteria",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        assert response.status_code == 200
        assert level_1 is bool(response.context["level_1_fields"])
        assert level_2 is bool(response.context["level_2_fields"])

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
    def test_post(self, client):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )

        url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        client.force_login(self.user)

        response = client.get(url)
        assert response.status_code == 200

        post_data = {criterion.administrative_criteria.key: True}
        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assert 1 == EvaluatedAdministrativeCriteria.objects.count()
        assert (
            criterion.administrative_criteria
            == EvaluatedAdministrativeCriteria.objects.first().administrative_criteria
        )

    def test_post_with_submission_freezed_at(self, client):
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

        client.force_login(self.user)

        post_data = {criterion.administrative_criteria.key: "on"}
        response = client.post(url, data=post_data)
        assert response.status_code == 403
        assert evaluated_job_application.evaluated_administrative_criteria.count() == 0

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
    def test_initial_data_form(self, client):
        # no preselected criteria
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.siae, self.user)
        url = reverse(
            "siae_evaluations_views:siae_select_criteria",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        client.force_login(self.user)

        response = client.get(url)
        assert response.status_code == 200

        for i in range(len(response.context["level_1_fields"])):
            assert (
                "checked" not in response.context["level_1_fields"][i].subwidgets[0].data["attrs"]
            ), f"{response.context['level_1_fields'][i].name} should not be checked"
        for i in range(len(response.context["level_2_fields"])):
            assert (
                "checked" not in response.context["level_2_fields"][i].subwidgets[0].data["attrs"]
            ), f"{response.context['level_2_fields'][i].name} should not be checked"

        # preselected criteria
        criterion = (
            evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.first()
        )
        EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_job_application,
            administrative_criteria=criterion.administrative_criteria,
        )

        response = client.get(url)
        assert response.status_code == 200

        assert "checked" in response.context["level_1_fields"][0].subwidgets[0].data["attrs"]
        for i in range(1, len(response.context["level_1_fields"])):
            assert (
                "checked" not in response.context["level_1_fields"][i].subwidgets[0].data["attrs"]
            ), f"{response.context['level_1_fields'][i].name} should not be checked"
        for i in range(len(response.context["level_2_fields"])):
            assert (
                "checked" not in response.context["level_2_fields"][i].subwidgets[0].data["attrs"]
            ), f"{response.context['level_2_fields'][i].name} should not be checked"


class TestSiaeUploadDocsView:
    def setup_method(self):
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.siae = membership.company

    def test_access_on_unknown_evaluated_job_application(self, client):
        client.force_login(self.user)
        response = client.get(
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": 10000},
            )
        )
        assert response.status_code == 404

    def test_access_without_ownership(self, client):
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

        client.force_login(self.user)
        response = client.get(
            reverse(
                "siae_evaluations_views:siae_upload_doc",
                kwargs={"evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk},
            )
        )
        assert response.status_code == 404

    def test_access_on_ended_campaign(self, client):
        client.force_login(self.user)

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
        response = client.get(url)
        assert response.status_code == 404

    @freeze_time("2022-09-14 11:11:11")
    def test_access(self, client):
        self.maxDiff = None
        client.force_login(self.user)

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
        response = client.get(url)
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

    def test_post(self, client, pdf_file):
        fake_now = timezone.now()
        client.force_login(self.user)

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
        response = client.get(url)

        post_data = {"proof": pdf_file}
        response = client.post(url, data=post_data)
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
        pdf_file.seek(0)
        with default_storage.open(evaluated_administrative_criteria.proof_id) as saved_file:
            assert saved_file.read() == pdf_file.read()

    def test_post_with_submission_freezed_at(self, client, pdf_file):
        fake_now = timezone.now()
        client.force_login(self.user)

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

        post_data = {"proof": pdf_file}
        response = client.post(url, data=post_data)
        assert response.status_code == 403
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.uploaded_at == fake_now - relativedelta(days=1)
        assert evaluated_administrative_criteria.proof == proof


class TestSiaeSubmitProofsView:
    def setup_method(self):
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.company = membership.company

    @staticmethod
    def url(evaluated_siae):
        return reverse(
            "siae_evaluations_views:siae_submit_proofs",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

    def test_is_submittable(self, client):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.company, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        client.force_login(self.user)

        with assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 1  # fetch siae membership
            + 1  # fetch siae infos
            + 1  # view starts, savepoint (ATOMIC_REQUESTS)
            + 3  # fetch evaluatedsiae, evaluatedjobapplication and evaluatedadministrativecriteria
            + 1  # fetch evaluation campaign
            + 1  # update evaluatedadministrativecriteria
            + 1  # update evaluatedsiae submission_freezed_at
            + 3  # fetch institution, siae and siae members for email notification
            + 1  # insert emails to ddets into emails table
            + 1  # email: _async_send_message task savepoint
            + 1  # fetch email details (and lock it)
            + 1  # update email status
            + 1  # email: release savepoint
            + 2  # update session, release savepoint
        ):
            response = client.post(self.url(evaluated_job_application.evaluated_siae))

        assert response.status_code == 302
        assert response.url == reverse("dashboard:index")
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.submitted_at is not None

    def test_is_not_submittable(self, client):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.company, self.user)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application, proof=None)
        client.force_login(self.user)

        response = client.post(self.url(evaluated_job_application.evaluated_siae))
        assert response.status_code == 302
        assert response.url == reverse(
            "siae_evaluations_views:siae_job_applications_list",
            kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
        )

    def test_is_submittable_with_accepted(self, client):
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

        client.force_login(self.user)
        response = client.post(self.url(evaluated_job_application.evaluated_siae))
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

    def test_is_submittable_with_a_forgotten_submitted_doc(self, client):
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

        client.force_login(self.user)
        response = client.post(self.url(submitted_job_application.evaluated_siae))
        assert response.status_code == 302
        assert response.url == "/dashboard/"

    def test_is_not_submittable_with_submission_freezed(self, client):
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(self.company, self.user)
        evaluated_administrative_criteria = EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application
        )
        # Freeze submission
        evaluated_job_application.evaluated_siae.evaluation_campaign.freeze(timezone.now())

        client.force_login(self.user)

        with assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 1  # fetch siae membership
            + 1  # fetch siae infos
            + 1  # fetch evaluatedsiae and see that submission is freezed, abort
            + 3  # savepoint, update session, release savepoint
        ):
            response = client.post(self.url(evaluated_job_application.evaluated_siae))

        assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
            ),
        )
        assertMessages(response, [messages.Message(messages.ERROR, "Impossible de soumettre les documents.")])
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.submitted_at is None

    def test_submitted_email(self, client):
        institution_membership = InstitutionMembershipFactory()
        evaluated_job_application = create_evaluated_siae_with_consistent_datas(
            self.company, self.user, institution=institution_membership.institution
        )
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application)
        client.force_login(self.user)
        response = client.post(self.url(evaluated_job_application.evaluated_siae))
        assert response.status_code == 302

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert (
            f"[DEV] [Contrôle a posteriori] La structure { evaluated_job_application.evaluated_siae.siae.kind } "
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

    def test_campaign_is_ended(self, client):
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

        client.force_login(self.user)
        response = client.post(self.url(evaluated_job_application.evaluated_siae))

        assert response.status_code == 404
        evaluated_administrative_criteria.refresh_from_db()
        assert evaluated_administrative_criteria.submitted_at is None


class TestSiaeCalendarView:
    def setup_method(self):
        membership = CompanyMembershipFactory()
        self.user = membership.user
        self.siae = membership.company

    def test_active_campaign_calendar(self, client):
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

        client.force_login(self.user)
        response = client.get(reverse("dashboard:index"))
        assertContains(response, calendar_url)

        response = client.get(calendar_url)
        assertContains(response, calendar_html)

        # Old campaigns don't have a calendar.
        evaluated_siae.evaluation_campaign.calendar.delete()
        response = client.get(reverse("dashboard:index"))
        assertNotContains(response, calendar_url)


class TestSiaeEvaluatedSiaeDetailView:
    def test_access(self, client):
        membership = CompanyMembershipFactory()
        user = membership.user
        siae = membership.company

        client.force_login(user)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(siae, user)
        evaluated_siae = evaluated_job_application.evaluated_siae
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        response = client.get(url)
        assert response.status_code == 404

        evaluation_campaign = evaluated_siae.evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = client.get(url)
        assert response.status_code == 200


class TestSiaeEvaluatedJobApplicationView:
    refusal_comment_txt = "Commentaire de la DDETS"

    def test_access(self, client):
        membership = CompanyMembershipFactory()
        user = membership.user
        siae = membership.company

        client.force_login(user)

        evaluated_job_application = create_evaluated_siae_with_consistent_datas(siae, user)
        evaluated_siae = evaluated_job_application.evaluated_siae
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        url = reverse(
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        response = client.get(url)
        assert response.status_code == 404

        evaluation_campaign = evaluated_siae.evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = client.get(url)
        assertNotContains(response, self.refusal_comment_txt)

        # Refusal comment is only displayed when state is refused
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
            submitted_at=timezone.now(),
        )
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])
        response = client.get(url)
        assertContains(response, self.refusal_comment_txt)
