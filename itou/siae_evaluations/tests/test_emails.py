from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.urls import reverse
from django.utils import dateformat, timezone
from freezegun import freeze_time

from itou.institutions.factories import InstitutionWith2MembershipFactory
from itou.siae_evaluations.emails import CampaignEmailFactory, InstitutionEmailFactory, SIAEEmailFactory
from itou.siae_evaluations.enums import EvaluatedAdministrativeCriteriaState
from itou.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from itou.siaes.factories import SiaeFactory, SiaeWith2MembershipsFactory


class TestInstitutionEmailFactory:
    def test_ratio_to_select(self):
        institution = InstitutionWith2MembershipFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution)

        date = timezone.localdate()
        email = CampaignEmailFactory(evaluation_campaign).ratio_to_select(date)

        assert email.to == list(u.email for u in institution.active_members)
        assert reverse("dashboard:index") in email.body
        assert (
            f"Le choix du taux de SIAE à contrôler est possible jusqu’au {dateformat.format(date, 'd E Y')}"
            in email.body
        )
        assert f"avant le {dateformat.format(date, 'd E Y')}" in email.subject

    def test_selected(self):
        siae = SiaeWith2MembershipsFactory()
        evaluated_siae = EvaluatedSiaeFactory(siae=siae, evaluation_campaign__evaluations_asked_at=timezone.now())
        email = SIAEEmailFactory(evaluated_siae).selected()

        assert email.to == list(u.email for u in evaluated_siae.siae.active_admin_members)
        assert email.subject == (
            "Contrôle a posteriori sur vos embauches réalisées "
            + f"du {dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, 'd E Y')} "
            + f"au {dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, 'd E Y')}"
        )
        assert siae.name in email.body
        assert siae.kind in email.body
        assert siae.convention.siret_signature in email.body
        assert dateformat.format(timezone.now() + relativedelta(weeks=6), "d E Y") in email.body

    def test_selected_siae(self):
        fake_now = timezone.now()
        institution = InstitutionWith2MembershipFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution, evaluations_asked_at=fake_now)

        email = CampaignEmailFactory(evaluation_campaign).selected_siae()
        assert email.to == list(u.email for u in institution.active_members)
        assert dateformat.format(fake_now + relativedelta(weeks=6), "d E Y") in email.body
        assert dateformat.format(evaluation_campaign.evaluated_period_start_at, "d E Y") in email.body
        assert dateformat.format(evaluation_campaign.evaluated_period_end_at, "d E Y") in email.body

    # See EvaluationCampaignManagerTest.test_close for notifications when siae
    # did not send proofs.

    @freeze_time("2023-01-23")
    def test_close_notifies_when_siae_has_negative_result(self, mailoutbox):
        institution = InstitutionWith2MembershipFactory(name="DDETS 01")
        campaign = EvaluationCampaignFactory(institution=institution)
        siae = SiaeWith2MembershipsFactory(name="les petits jardins")
        evaluated_siae = EvaluatedSiaeFactory(
            siae=siae,
            evaluation_campaign=campaign,
            reviewed_at=timezone.now() - relativedelta(days=60),
            final_reviewed_at=timezone.now() - relativedelta(days=20),
        )
        evaluated_jobapp = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_jobapp,
            uploaded_at=timezone.now() - relativedelta(days=21, minutes=1),
            submitted_at=timezone.now() - relativedelta(days=21),
            review_state=EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )

        campaign.close()

        [institution_email] = mailoutbox

        assert sorted(institution_email.to) == sorted(institution.active_members.values_list("email", flat=True))
        assert institution_email.subject == "[Contrôle a posteriori] Notification des sanctions"
        assert institution_email.body == (
            "Bonjour,\n\n"
            "Suite au dernier contrôle a posteriori, une ou plusieurs SIAE de votre département ont obtenu un "
            "résultat négatif.\n"
            "Conformément au  Décret n° 2021-1128 du 30 août 2021 relatif à l'insertion par l'activité économique, "
            "les manquements constatés ainsi que les sanctions envisagées doivent être notifiés aux SIAE.\n\n"
            "Veuillez vous connecter sur votre espace des emplois de l’inclusion afin d’effectuer cette démarche.\n"
            f"http://127.0.0.1:8000/siae_evaluation/institution_evaluated_siae_list/{campaign.pk}/\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://127.0.0.1:8000"
        )

    def test_close_does_not_notify_when_siae_has_been_notified(self, mailoutbox):
        institution = InstitutionWith2MembershipFactory(name="DDETS 01")
        campaign = EvaluationCampaignFactory(institution=institution)
        siae = SiaeWith2MembershipsFactory(name="les petits jardins")
        evaluated_siae = EvaluatedSiaeFactory(
            siae=siae,
            evaluation_campaign=campaign,
            reviewed_at=timezone.now() - relativedelta(days=60),
            final_reviewed_at=timezone.now() - relativedelta(days=20),
            notified_at=timezone.now() - relativedelta(days=10),
        )
        evaluated_jobapp = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_jobapp,
            uploaded_at=timezone.now() - relativedelta(days=21, minutes=1),
            submitted_at=timezone.now() - relativedelta(days=21),
            review_state=EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )

        campaign.close()

        assert [] == mailoutbox

    def test_close_does_not_notify_when_siae_has_positive_result(self, mailoutbox):
        institution = InstitutionWith2MembershipFactory(name="DDETS 01")
        campaign = EvaluationCampaignFactory(institution=institution)
        siae = SiaeWith2MembershipsFactory(name="les petits jardins")
        evaluated_siae = EvaluatedSiaeFactory(
            siae=siae,
            evaluation_campaign=campaign,
            reviewed_at=timezone.now() - relativedelta(days=50),
            final_reviewed_at=timezone.now() - relativedelta(days=50),
        )
        evaluated_jobapp = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_jobapp,
            uploaded_at=timezone.now() - relativedelta(days=51, minutes=1),
            submitted_at=timezone.now() - relativedelta(days=51),
            review_state=EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )

        campaign.close()

        assert [] == mailoutbox

    def test_submitted_by_siae(self):
        institution = InstitutionWith2MembershipFactory()
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__institution=institution)
        email = InstitutionEmailFactory(evaluated_siae).submitted_by_siae()

        assert evaluated_siae.siae.kind in email.subject
        assert evaluated_siae.siae.name in email.subject
        assert evaluated_siae.siae.kind in email.body
        assert evaluated_siae.siae.name in email.body
        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == len(institution.active_members)


class TestSIAEEmails:
    def test_reviewed(self):
        siae = SiaeFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=siae)
        email = SIAEEmailFactory(evaluated_siae).reviewed()

        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == len(evaluated_siae.siae.active_admin_members)
        assert email.to[0] == evaluated_siae.siae.active_admin_members.first().email
        assert evaluated_siae.siae.kind in email.subject
        assert evaluated_siae.siae.name in email.subject
        assert str(evaluated_siae.siae.id) in email.subject
        assert evaluated_siae.siae.kind in email.body
        assert evaluated_siae.siae.name in email.body
        assert str(evaluated_siae.siae.id) in email.body
        assert evaluated_siae.evaluation_campaign.institution.name in email.body
        assert dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, "d E Y") in email.body
        assert dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, "d E Y") in email.body
        assert "la conformité des justificatifs que vous avez" in email.body

        email = SIAEEmailFactory(evaluated_siae).reviewed(adversarial=True)
        assert "la conformité des nouveaux justificatifs que vous avez" in email.body

    def test_refused(self):
        siae = SiaeFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=siae)
        email = SIAEEmailFactory(evaluated_siae).refused()

        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == len(evaluated_siae.siae.active_admin_members)
        assert email.to[0] == evaluated_siae.siae.active_admin_members.first().email
        assert evaluated_siae.siae.kind in email.subject
        assert evaluated_siae.siae.name in email.subject
        assert str(evaluated_siae.siae.id) in email.subject
        assert evaluated_siae.siae.kind in email.body
        assert evaluated_siae.siae.name in email.body
        assert str(evaluated_siae.siae.id) in email.body
        assert evaluated_siae.evaluation_campaign.institution.name in email.body
        assert dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, "d E Y") in email.body
        assert dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, "d E Y") in email.body

    def test_adversarial_stage(self):
        siae = SiaeFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=siae)
        email = SIAEEmailFactory(evaluated_siae).adversarial_stage()

        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == len(evaluated_siae.siae.active_admin_members)
        assert email.to[0] == evaluated_siae.siae.active_admin_members.first().email
        assert evaluated_siae.siae.kind in email.subject
        assert evaluated_siae.siae.name in email.subject
        assert str(evaluated_siae.siae.id) in email.subject
        assert evaluated_siae.siae.kind in email.body
        assert evaluated_siae.siae.name in email.body
        assert str(evaluated_siae.siae.id) in email.body
        assert evaluated_siae.evaluation_campaign.institution.name in email.body
        assert dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, "d E Y") in email.body
        assert dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, "d E Y") in email.body
