import collections

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.urls import reverse
from django.utils import dateformat, timezone
from freezegun import freeze_time

from itou.siae_evaluations.emails import CampaignEmailFactory, InstitutionEmailFactory, SIAEEmailFactory
from itou.siae_evaluations.enums import EvaluatedAdministrativeCriteriaState
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.institutions.factories import InstitutionWith2MembershipFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)


@pytest.mark.usefixtures("unittest_compatibility")
class TestInstitutionEmailFactory:
    def test_ratio_to_select(self):
        institution = InstitutionWith2MembershipFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution)

        email = CampaignEmailFactory(evaluation_campaign).ratio_to_select()

        assert collections.Counter(email.to) == collections.Counter(u.email for u in institution.active_members)
        assert reverse("dashboard:index") in email.body
        assert "Vous disposez de 4 semaines pour choisir votre taux de SIAE à contrôler." in email.body
        assert "Vous disposez de 4 semaines pour sélectionner votre échantillon." in email.subject

    def test_selected(self):
        company = CompanyWith2MembershipsFactory()
        evaluated_siae = EvaluatedSiaeFactory(siae=company, evaluation_campaign__evaluations_asked_at=timezone.now())
        email = SIAEEmailFactory(evaluated_siae).selected()

        assert email.to == list(u.email for u in evaluated_siae.siae.active_admin_members)
        assert email.subject == (
            "[DEV] Contrôle a posteriori sur vos embauches réalisées "
            + f"du {dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_start_at, 'd E Y')} "
            + f"au {dateformat.format(evaluated_siae.evaluation_campaign.evaluated_period_end_at, 'd E Y')}"
        )
        assert company.name in email.body
        assert company.kind in email.body
        assert company.convention.siret_signature in email.body

    def test_selected_siae(self):
        fake_now = timezone.now()
        institution = InstitutionWith2MembershipFactory()
        evaluation_campaign = EvaluationCampaignFactory(institution=institution, evaluations_asked_at=fake_now)

        email = CampaignEmailFactory(evaluation_campaign).selected_siae()
        assert collections.Counter(email.to) == collections.Counter(u.email for u in institution.active_members)
        assert dateformat.format(evaluation_campaign.evaluated_period_start_at, "d E Y") in email.body
        assert dateformat.format(evaluation_campaign.evaluated_period_end_at, "d E Y") in email.body

    # See EvaluationCampaignManagerTest.test_close for notifications when siae
    # did not send proofs.

    @freeze_time("2023-01-23")
    def test_close_notifies_when_siae_has_negative_result(self, django_capture_on_commit_callbacks, mailoutbox):
        institution = InstitutionWith2MembershipFactory(name="DDETS 01")
        campaign = EvaluationCampaignFactory(pk=1, institution=institution)
        company = CompanyWith2MembershipsFactory(pk=1000, name="les petits jardins")
        evaluated_siae = EvaluatedSiaeFactory(
            siae=company,
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

        with django_capture_on_commit_callbacks(execute=True):
            campaign.close()

        [siae_refused_email, institution_email] = mailoutbox

        assert sorted(institution_email.to) == sorted(institution.active_members.values_list("email", flat=True))
        assert institution_email.subject == "[DEV] [Contrôle a posteriori] Notification des sanctions"
        assert institution_email.body == self.snapshot(name="sanction notification email")

        assert siae_refused_email.subject == "[DEV] Résultat du contrôle - EI les petits jardins ID-1000"
        assert siae_refused_email.body == self.snapshot(name="refused result email")

    def test_close_does_not_notify_when_siae_has_been_notified(self, django_capture_on_commit_callbacks, mailoutbox):
        institution = InstitutionWith2MembershipFactory(name="DDETS 01")
        campaign = EvaluationCampaignFactory(institution=institution)
        company = CompanyWith2MembershipsFactory(name="les petits jardins")
        evaluated_siae = EvaluatedSiaeFactory(
            siae=company,
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

        with django_capture_on_commit_callbacks(execute=True):
            campaign.close()

        assert [] == mailoutbox

    @freeze_time("2023-06-07")
    def test_close_notify_when_siae_has_positive_result_in_adversarial_phase(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        institution = InstitutionWith2MembershipFactory(name="DDETS 01")
        campaign = EvaluationCampaignFactory(institution=institution)
        company = CompanyWith2MembershipsFactory(pk=1000, name="les petits jardins")
        evaluated_siae = EvaluatedSiaeFactory(
            siae=company,
            evaluation_campaign=campaign,
            reviewed_at=timezone.now() - relativedelta(days=55),
            final_reviewed_at=timezone.now() - relativedelta(days=50),
        )
        evaluated_jobapp = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_jobapp,
            uploaded_at=timezone.now() - relativedelta(days=51, minutes=1),
            submitted_at=timezone.now() - relativedelta(days=51),
            review_state=EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )

        with django_capture_on_commit_callbacks(execute=True):
            campaign.close()

        [siae_accepted_email] = mailoutbox
        assert siae_accepted_email.subject == "[DEV] Résultat du contrôle - EI les petits jardins ID-1000"
        assert siae_accepted_email.body == self.snapshot(name="accepted result email")

    def test_close_does_not_notify_when_siae_has_positive_result_in_amicable_phase(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        institution = InstitutionWith2MembershipFactory(name="DDETS 01")
        campaign = EvaluationCampaignFactory(institution=institution)
        company = CompanyWith2MembershipsFactory(pk=1000, name="les petits jardins")
        reviewed_at = timezone.now() - relativedelta(days=50)
        evaluated_siae = EvaluatedSiaeFactory(
            siae=company,
            evaluation_campaign=campaign,
            reviewed_at=reviewed_at,
            final_reviewed_at=reviewed_at,
        )
        evaluated_jobapp = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_jobapp,
            uploaded_at=timezone.now() - relativedelta(days=51, minutes=1),
            submitted_at=timezone.now() - relativedelta(days=51),
            review_state=EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )

        with django_capture_on_commit_callbacks(execute=True):
            campaign.close()
        assert mailoutbox == []

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
    def test_accepted(self):
        company = CompanyFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=company)
        email = SIAEEmailFactory(evaluated_siae).accepted()

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

        email = SIAEEmailFactory(evaluated_siae).accepted(adversarial=True)
        assert "la conformité des nouveaux justificatifs que vous avez" in email.body

    def test_refused(self):
        company = CompanyFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=company)
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
        company = CompanyFactory(with_membership=True)
        evaluated_siae = EvaluatedSiaeFactory(siae=company)
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
