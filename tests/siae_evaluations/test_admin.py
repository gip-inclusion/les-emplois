from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNumQueries

from itou.siae_evaluations import enums as evaluation_enums
from tests.companies.factories import CompanyMembershipFactory
from tests.institutions.factories import InstitutionFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import ItouStaffFactory
from tests.utils.test import BASE_NUM_QUERIES, get_rows_from_streaming_response


class TestEvaluationCampaignAdmin:
    @freeze_time("2022-12-07 11:11:00")
    def test_export(self, client):
        institution = InstitutionFactory(name="DDETS 01", department="01")
        campaign1 = EvaluationCampaignFactory(name="Contrôle 01/01/2022", institution=institution)
        campaign1_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign1,
            siae__name="les jardins",
            siae__siret="00000000000040",
            siae__convention__siret_signature="00000000000032",
            siae__phone="",
        )
        CompanyMembershipFactory(company=campaign1_siae.siae, user__email="campaign1+1@beta.gouv.fr")
        CompanyMembershipFactory(company=campaign1_siae.siae, user__email="campaign1+2@beta.gouv.fr")
        campaign2 = EvaluationCampaignFactory(name="Contrôle 01/01/2021", institution=institution)
        campaign2_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign2,
            siae__name="les trucs du bazar",
            siae__siret="12345678900040",
            siae__convention__siret_signature="12345678900032",
            siae__phone="0612345678",
            reviewed_at=timezone.now(),
        )
        CompanyMembershipFactory(company=campaign2_siae.siae, user__email="campaign2@beta.gouv.fr")
        campaign3 = EvaluationCampaignFactory(
            name="Contrôle 01/01/2019", institution=institution, ended_at=timezone.now()
        )
        campaign3_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign3,
            siae__name="les bidules",
            siae__siret="11111111100040",
            siae__convention__siret_signature="11111111100032",
            siae__phone="0611111111",
            notified_at=timezone.now(),
            notification_text="Justificatifs mangés par le chat",
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.MISSING_PROOF,
        )
        CompanyMembershipFactory(company=campaign3_siae.siae, user__email="campaign3@beta.gouv.fr")
        campaign4 = EvaluationCampaignFactory(name="Contrôle 01/01/2018", institution=institution)
        campaign4_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign4,
            siae__name="les machins",
            siae__convention__siret_signature="22222222200032",
            siae__phone="0622222222",
            reviewed_at=timezone.now() - relativedelta(days=2),
            final_reviewed_at=timezone.now() - relativedelta(days=1),
        )
        EvaluatedSiaeFactory(
            evaluation_campaign=campaign4,
            siae__name="les machins le retour",
            siae__convention__siret_signature="22222222200033",
            siae__phone="0633333333",
        )
        campaign4_jobapp = EvaluatedJobApplicationFactory.create(evaluated_siae=campaign4_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=campaign4_jobapp,
            uploaded_at=timezone.now() - relativedelta(days=1),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        CompanyMembershipFactory(company=campaign4_siae.siae, user__email="campaign4@beta.gouv.fr")
        # Not selected.
        EvaluatedSiaeFactory(
            evaluation_campaign__name="Contrôle 02/02/2020", evaluation_campaign__institution__department="02"
        )
        admin_user = ItouStaffFactory(is_superuser=True)
        client.force_login(admin_user)
        with assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # SELECT set_config()
            + 1  # Load Django session
            + 1  # Load user
            + 1  # Count the filtered results (paginator)
            + 1  # Count the full results
            + 1  # Fetch evaluated siae and related evaludation_campaign, siae, convention
            + 1  # Prefetch evaludated job applications
            + 1  # Prefetch corresponding administrative criteria
            + 1  # Prefetch siae memberships
            + 1  # Prefetch users of siae memberships
        ):
            response = client.post(
                reverse("admin:siae_evaluations_evaluationcampaign_changelist"),
                {
                    "action": "export_siaes",
                    "select_across": "0",
                    "index": "0",
                    "_selected_action": [
                        campaign1.pk,
                        campaign2.pk,
                        campaign3.pk,
                        campaign4.pk,
                    ],
                },
            )
            excel_export = get_rows_from_streaming_response(response)
        assert response.status_code == 200
        assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert (
            response["Content-Disposition"] == 'attachment; filename="export-siaes-campagnes_2022-12-07_12-11-00.xlsx"'
        )
        assert excel_export == [
            [
                "Campagne",
                "SIRET signature",
                "Type",
                "Nom",
                "Département",
                "Emails administrateurs",
                "Numéro de téléphone",
                "État du contrôle",
                "Phase du contrôle",
            ],
            # campaign1
            [
                "Contrôle 01/01/2022",
                "00000000000032",
                "EI",
                "les jardins",
                "14",
                "campaign1+1@beta.gouv.fr, campaign1+2@beta.gouv.fr",
                "",
                "PENDING",
                "Phase amiable",
            ],
            # campaign2
            [
                "Contrôle 01/01/2021",
                "12345678900032",
                "EI",
                "les trucs du bazar",
                "14",
                "campaign2@beta.gouv.fr",
                "0612345678",
                "PENDING",
                "Phase contradictoire",
            ],
            # campaign3
            [
                "Contrôle 01/01/2019",
                "11111111100032",
                "EI",
                "les bidules",
                "14",
                "campaign3@beta.gouv.fr",
                "0611111111",
                "REFUSED",
                "Campagne terminée",
            ],
            # campaign4
            [
                "Contrôle 01/01/2018",
                "22222222200032",
                "EI",
                "les machins",
                "14",
                "campaign4@beta.gouv.fr",
                "0622222222",
                "ACCEPTED",
                "Contrôle terminé",
            ],
            [
                "Contrôle 01/01/2018",
                "22222222200033",
                "EI",
                "les machins le retour",
                "14",
                "",
                "0633333333",
                "PENDING",
                "Phase amiable",
            ],
        ]

    def test_freeze(self, client):
        campaign1 = EvaluationCampaignFactory(institution__department="01")
        campaign1_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign1,
            submission_freezed_at=timezone.now() - relativedelta(days=1),
        )
        campaign2 = EvaluationCampaignFactory(institution__department="02")
        campaign2_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign2,
        )
        admin_user = ItouStaffFactory(is_superuser=True)
        client.force_login(admin_user)
        with assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # SELECT set_config()
            + 1  # Load Django session
            + 1  # Load user
            + 1  # Count the filtered results (paginator)
            + 1  # Count the full results
            + 1  # Fetch selected evaluation_campaigns
            + 2 * 2  # For each campaign: update EvaluatedSiae & check if a notification is needed
        ):
            response = client.post(
                reverse("admin:siae_evaluations_evaluationcampaign_changelist"),
                {
                    "action": "freeze",
                    "select_across": "0",
                    "index": "0",
                    "_selected_action": [
                        campaign1.pk,
                        campaign2.pk,
                    ],
                },
            )
        assert response.status_code == 302
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    "Les soumissions des SIAEs sont maintenant bloquées pour les campagnes sélectionnées.",
                )
            ],
        )
        campaign1_siae.refresh_from_db()
        assert campaign1_siae.submission_freezed_at is not None
        campaign2_siae.refresh_from_db()
        assert campaign2_siae.submission_freezed_at is not None


def test_evaluated_job_application_state_display(admin_client):
    evaluated_job_app = EvaluatedJobApplicationFactory(
        complete=True,
        evaluated_siae__evaluation_campaign__evaluations_asked_at=timezone.now() - timedelta(days=60),
    )
    response = admin_client.get(
        reverse(
            "admin:siae_evaluations_evaluatedjobapplication_change",
            kwargs={"object_id": evaluated_job_app.pk},
        )
    )
    assertContains(
        response,
        """
        <div class="flex-container">
          <label>State :</label>
          <div class="readonly">SUBMITTED</div>
        </div>
        """,
        html=True,
        count=1,
    )


def test_evaluated_job_application_state_display_in_evaluated_siae_admin(admin_client):
    evaluated_job_app = EvaluatedJobApplicationFactory(
        complete=True,
        evaluated_siae__evaluation_campaign__evaluations_asked_at=timezone.now() - timedelta(days=60),
    )
    response = admin_client.get(
        reverse(
            "admin:siae_evaluations_evaluatedsiae_change",
            kwargs={"object_id": evaluated_job_app.evaluated_siae.pk},
        )
    )
    # Check evaluated job app state is properly displayed in its inline table
    assertContains(
        response,
        """
        <td class="field-state">
          <p>SUBMITTED</p>
        </td>
        """,
        html=True,
        count=1,
    )
