from dateutil.relativedelta import relativedelta
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from itou.institutions.factories import InstitutionFactory, InstitutionWith2MembershipFactory
from itou.institutions.models import Institution
from itou.siae_evaluations.factories import EvaluationCampaignFactory
from itou.siae_evaluations.models import EvaluationCampaign, create_campaigns, validate_institution


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
    def test_institution_with_campaign_in_progress(self):
        institution = InstitutionFactory()
        EvaluationCampaignFactory(institution=institution)
        self.assertTrue(EvaluationCampaign.objects.has_active_campaign(institution))

    def test_institution_without_any_campaign(self):
        institution = InstitutionFactory()
        self.assertFalse(EvaluationCampaign.objects.has_active_campaign(institution))

    def test_institution_with_ended_campaign(self):
        ended_at = timezone.now() - relativedelta(years=1)
        institution = InstitutionFactory()
        EvaluationCampaignFactory(institution=institution, ended_at=ended_at)
        self.assertFalse(EvaluationCampaign.objects.has_active_campaign(institution))

    def test_institution_with_ended_and_in_progress_campaign(self):
        now = timezone.now()
        ended_at = now - relativedelta(years=1)
        institution = InstitutionFactory()
        EvaluationCampaignFactory(
            institution=institution,
            ended_at=ended_at,
        )
        EvaluationCampaignFactory(
            institution=institution,
        )
        self.assertTrue(EvaluationCampaign.objects.has_active_campaign(institution))

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
                institution = InstitutionFactory(kind=kind)
                self.assertEqual(
                    0, create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at)
                )
                for box in mail.outbox:
                    print(box.to)
                    print(box.subject)
                self.assertEqual(len(mail.outbox), 0)

        # institution DDETS
        institution = InstitutionWith2MembershipFactory(kind=Institution.Kind.DDETS)
        self.assertEqual(
            1,
            create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at),
        )
        self.assertEqual(
            EvaluationCampaign.objects.filter(institution=institution).first(),
            EvaluationCampaign.objects.first(),
        )

        # An email should have been sent to the institution members.

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 2)
        self.assertIn(
            "Le choix du taux de SIAE à contrôler est possible jusqu’au " f"{ratio_selection_end_at.strftime('%d')}",
            email.body,
        )

        # mass mail send
        # made 48 institutions * 2 members = 96 emails addresses
        # 96 emails addresses splitted in 2 lists of 48 items
        InstitutionWith2MembershipFactory.create_batch(47, kind=Institution.Kind.DDETS)
        create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at)
        self.assertEqual(len(mail.outbox), 3)
        email = mail.outbox[1]
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 48)
        email = mail.outbox[2]
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 48)
