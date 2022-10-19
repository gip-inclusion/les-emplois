from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from itou.institutions.factories import InstitutionMembershipFactory
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.factories import EvaluatedSiaeFactory
from itou.siaes.factories import SiaeMembershipFactory


class EvaluatedSiaeSanctionViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        institution_membership = InstitutionMembershipFactory(institution__name="DDETS 87")
        cls.institution_user = institution_membership.user
        siae_membership = SiaeMembershipFactory(siae__name="Les petits jardins")
        cls.siae_user = siae_membership.user
        cls.evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            evaluation_campaign__institution=institution_membership.institution,
            evaluation_campaign__name="Contrôle 2022",
            siae=siae_membership.siae,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat. Séparé de son chat pendant une journée.",
        )

    def assertSanctionContent(self, response):
        self.assertContains(
            response,
            "<h1>Résultat de la campagne de contrôle a posteriori Contrôle 2022</h1>",
            count=1,
        )
        self.assertContains(
            response,
            '<b>Résultat :</b> <b class="text-danger">Négatif</b>',
            count=1,
        )
        self.assertContains(
            response,
            '<b>Raison principale :</b> <b class="text-info">Pièce justificative incorrecte</b>',
            count=1,
        )
        self.assertContains(
            response,
            """
            <b>Commentaire de votre DDETS</b>
            <div class="card">
                <div class="card-body">A envoyé une photo de son chat. Séparé de son chat pendant une journée.</div>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_anonymous_view_siae(self):
        url = reverse(
            "siae_evaluations_views:siae_sanction",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        response = self.client.get(url)
        self.assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_anonymous_view_institution(self):
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_sanction",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        response = self.client.get(url)
        self.assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_view_as_institution(self):
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)

    def test_view_as_other_institution(self):
        other = InstitutionMembershipFactory()
        self.client.force_login(other.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_view_as_siae(self):
        self.client.force_login(self.siae_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)

    def test_view_as_other_siae(self):
        siae_membership = SiaeMembershipFactory()
        self.client.force_login(siae_membership.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        assert response.status_code == 404
