from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries

from itou.siae_evaluations.factories import EvaluatedSiaeFactory, EvaluationCampaignFactory
from itou.siaes.factories import SiaeMembershipFactory
from itou.users.factories import JobSeekerFactory


class TestEvaluationCampaignAdmin:
    @freeze_time("2022-12-07 11:11:00")
    def test_export(self, client):
        campaign1 = EvaluationCampaignFactory(name="Contrôle 01/01/2022", institution__name="DDETS 01")
        campaign1_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign1,
            siae__name="les jardins",
            siae__siret="00000000000040",
            siae__convention__siret_signature="00000000000032",
            siae__phone="",
        )
        SiaeMembershipFactory(siae=campaign1_siae.siae, user__email="campaign1+1@beta.gouv.fr")
        SiaeMembershipFactory(siae=campaign1_siae.siae, user__email="campaign1+2@beta.gouv.fr")
        campaign2 = EvaluationCampaignFactory(name="Contrôle 01/01/2021", institution__name="DDETS 01")
        campaign2_siae = EvaluatedSiaeFactory(
            evaluation_campaign=campaign2,
            siae__name="les trucs du bazar",
            siae__siret="12345678900040",
            siae__convention__siret_signature="12345678900032",
            siae__phone="0612345678",
        )
        SiaeMembershipFactory(siae=campaign2_siae.siae, user__email="campaign2@beta.gouv.fr")
        EvaluatedSiaeFactory(evaluation_campaign__name="Contrôle 02/02/2020")
        admin_user = JobSeekerFactory(is_staff=True, is_superuser=True)
        client.force_login(admin_user)
        with assertNumQueries(
            1  # Load Django session
            + 1  # Load user
            + 1  # Count the filtered results (paginator)
            + 1  # Count the full results
            + 1  # Fetch evaluation campaigns
            + 1  # Prefetch evaluated siaes
            + 1  # Prefetch job applications
            + 1  # Prefetch siaes
            + 1  # Prefetch siae memberships
            + 1  # Prefetch users of siae memberships
            + 1  # Prefetch siae conventions
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
                    ],
                },
            )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/csv"
        assert (
            response["Content-Disposition"]
            == 'attachment; filename="export-siaes-campagnes-2022-12-07T11-11-00+00-00.csv"'
        )
        assert response.content.decode(response.charset) == (
            "Campagne,SIRET signature,Type,Nom,Département,Emails administrateurs,Numéro de téléphone,"
            "État du contrôle\r\n"
            # campaign1
            "Contrôle 01/01/2022,00000000000032,EI,les jardins,14,"
            '"campaign1+1@beta.gouv.fr, campaign1+2@beta.gouv.fr",,PENDING\r\n'
            # campaign2
            "Contrôle 01/01/2021,12345678900032,EI,les trucs du bazar,14,campaign2@beta.gouv.fr,0612345678,PENDING\r\n"
        )
