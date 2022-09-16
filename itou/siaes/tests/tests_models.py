from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from itou.job_applications.factories import JobApplicationFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.enums import ContractType, SiaeKind
from itou.siaes.factories import (
    SiaeAfterGracePeriodFactory,
    SiaeFactory,
    SiaePendingGracePeriodFactory,
    SiaeWith2MembershipsFactory,
    SiaeWith4MembershipsFactory,
    SiaeWithMembershipAndJobsFactory,
)
from itou.siaes.models import Siae, SiaeJobDescription


class SiaeFactoriesTest(TestCase):
    def test_siae_with_membership_factory(self):
        siae = SiaeFactory(with_membership=True)
        self.assertEqual(siae.members.count(), 1)
        user = siae.members.get()
        self.assertTrue(siae.has_admin(user))

    def test_siae_with_membership_and_jobs_factory(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        self.assertEqual(siae.jobs.count(), 2)

    def test_siae_with_2_memberships_factory(self):
        siae = SiaeWith2MembershipsFactory()
        self.assertEqual(siae.members.count(), 2)
        self.assertEqual(siae.active_members.count(), 2)
        self.assertEqual(siae.active_admin_members.count(), 1)
        admin_user = siae.active_admin_members.get()
        self.assertTrue(siae.has_admin(admin_user))
        all_users = list(siae.members.all())
        self.assertEqual(len(all_users), 2)
        all_users.remove(admin_user)
        self.assertEqual(len(all_users), 1)
        regular_user = all_users[0]
        self.assertFalse(siae.has_admin(regular_user))

    def test_siae_with_4_memberships_factory(self):
        siae = SiaeWith4MembershipsFactory()
        self.assertEqual(siae.members.count(), 4)
        self.assertEqual(siae.active_members.count(), 2)
        self.assertEqual(siae.active_admin_members.count(), 1)


class SiaeModelTest(TestCase):
    def test_accept_survey_url(self):

        siae = SiaeFactory(kind=SiaeKind.EI, department="57")
        url = siae.accept_survey_url
        self.assertTrue(url.startswith(f"{settings.TALLY_URL}/r/"))
        self.assertIn(f"id_siae={siae.pk}", url)
        self.assertIn("type_siae=Entreprise+d%27insertion", url)
        self.assertIn("region=Grand+Est", url)
        self.assertIn("departement=57", url)

        # Ensure that the URL does not break when there is no department.
        siae = SiaeFactory(kind=SiaeKind.AI, department="")
        self.assertTrue(url.startswith(f"{settings.TALLY_URL}/r/"))
        url = siae.accept_survey_url
        self.assertIn(f"id_siae={siae.pk}", url)
        self.assertIn("type_siae=Association+interm%C3%A9diaire", url)
        self.assertIn("region=", url)
        self.assertIn("departement=", url)

    def test_siren_and_nic(self):
        siae = SiaeFactory(siret="12345678900001")
        self.assertEqual(siae.siren, "123456789")
        self.assertEqual(siae.siret_nic, "00001")

    def test_is_subject_to_eligibility_rules(self):
        siae = SiaeFactory(kind=SiaeKind.GEIQ)
        self.assertFalse(siae.is_subject_to_eligibility_rules)

        siae = SiaeFactory(kind=SiaeKind.EI)
        self.assertTrue(siae.is_subject_to_eligibility_rules)

    def test_should_have_convention(self):
        siae = SiaeFactory(kind=SiaeKind.ACIPHC)
        self.assertFalse(siae.should_have_convention)

        siae = SiaeFactory(kind=SiaeKind.EI)
        self.assertTrue(siae.should_have_convention)

    def test_has_members(self):
        siae1 = SiaeFactory()
        siae2 = SiaeFactory(with_membership=True)

        self.assertFalse(siae1.has_members)
        self.assertTrue(siae2.has_members)

    def test_has_member(self):
        siae1 = SiaeFactory(with_membership=True)
        siae2 = SiaeFactory(with_membership=True)

        user1 = siae1.members.get()
        user2 = siae2.members.get()

        self.assertTrue(siae1.has_member(user1))
        self.assertFalse(siae1.has_member(user2))

        self.assertTrue(siae2.has_member(user2))
        self.assertFalse(siae2.has_member(user1))

    def test_active_members(self):
        siae = SiaeWith2MembershipsFactory(membership2__is_active=False)
        user_with_active_membership = siae.members.first()
        user_with_inactive_membership = siae.members.last()

        self.assertNotIn(user_with_inactive_membership, siae.active_members)
        self.assertIn(user_with_active_membership, siae.active_members)

        # Deactivate a user
        user_with_active_membership.is_active = False
        user_with_active_membership.save()

        self.assertNotIn(user_with_active_membership, siae.active_members)

    def test_active_admin_members(self):
        """
        Test that if a user is admin of siae_1 and regular user
        of siae_2 he is not considered as admin of siae_2.
        """
        siae_1 = SiaeFactory(with_membership=True)
        siae_1_admin_user = siae_1.members.first()
        siae_2 = SiaeFactory(with_membership=True)
        siae_2.members.add(siae_1_admin_user)

        self.assertIn(siae_1_admin_user, siae_1.active_admin_members)
        self.assertNotIn(siae_1_admin_user, siae_2.active_admin_members)

    def test_has_admin(self):
        siae_1 = SiaeWith2MembershipsFactory()
        siae_1_admin_user = siae_1.active_admin_members.get()
        siae1_regular_user = siae_1.active_members.exclude(pk=siae_1_admin_user.pk).get()
        siae_2 = SiaeWith2MembershipsFactory(membership2__user=siae_1_admin_user)

        self.assertTrue(siae_1.has_member(siae_1_admin_user))
        self.assertTrue(siae_1.has_admin(siae_1_admin_user))

        self.assertTrue(siae_1.has_member(siae1_regular_user))
        self.assertFalse(siae_1.has_admin(siae1_regular_user))

        self.assertTrue(siae_2.has_member(siae_1_admin_user))
        self.assertFalse(siae_2.has_admin(siae_1_admin_user))

    def test_new_signup_activation_email_to_official_contact(self):

        siae = SiaeFactory(with_membership=True)
        token = siae.get_token()
        with mock.patch("itou.utils.tokens.SiaeSignupTokenGenerator.make_token", return_value=token):

            factory = RequestFactory()
            request = factory.get("/")

            message = siae.new_signup_activation_email_to_official_contact(request)
            message.send()

            self.assertEqual(len(mail.outbox), 1)
            email = mail.outbox[0]
            self.assertIn("Un nouvel utilisateur souhaite rejoindre votre structure", email.subject)
            self.assertIn("Ouvrez le lien suivant pour procéder à l'inscription", email.body)
            self.assertIn(siae.signup_magic_link, email.body)
            self.assertIn(siae.display_name, email.body)
            self.assertIn(siae.siret, email.body)
            self.assertIn(siae.kind, email.body)
            self.assertIn(siae.auth_email, email.body)
            self.assertNotIn(siae.email, email.body)
            self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
            self.assertEqual(len(email.to), 1)
            self.assertEqual(email.to[0], siae.auth_email)

    def test_activate_your_account_email(self):
        siae = SiaeFactory(with_membership=True)
        with self.assertRaises(ValidationError):
            siae.activate_your_account_email()

        siae = SiaeFactory(auth_email="")
        with self.assertRaises(ValidationError):
            siae.activate_your_account_email()

        siae = SiaeFactory()
        email = siae.activate_your_account_email()
        self.assertEqual(email.to, [siae.auth_email])
        self.assertIn(siae.kind, email.subject)
        self.assertIn(siae.name, email.subject)
        self.assertIn(siae.kind, email.body)
        self.assertIn(siae.siret, email.body)
        self.assertIn(reverse("signup:siae_select"), email.body)

    def test_deactivation_queryset_methods(self):
        siae = SiaeFactory()
        self.assertEqual(Siae.objects.count(), 1)
        self.assertEqual(Siae.objects.active().count(), 1)
        self.assertEqual(Siae.objects.active_or_in_grace_period().count(), 1)
        siae.delete()
        self.assertEqual(Siae.objects.count(), 0)

        siae = SiaePendingGracePeriodFactory()
        self.assertEqual(Siae.objects.count(), 1)
        self.assertEqual(Siae.objects.active().count(), 0)
        self.assertEqual(Siae.objects.active_or_in_grace_period().count(), 1)
        siae.delete()
        self.assertEqual(Siae.objects.count(), 0)

        siae = SiaeAfterGracePeriodFactory()
        self.assertEqual(Siae.objects.count(), 1)
        self.assertEqual(Siae.objects.active().count(), 0)
        self.assertEqual(Siae.objects.active_or_in_grace_period().count(), 0)
        siae.delete()
        self.assertEqual(Siae.objects.count(), 0)

    def test_active_member_with_many_memberships(self):
        siae1 = SiaeWith2MembershipsFactory(membership2__is_active=False)
        user = siae1.members.filter(siaemembership__is_admin=False).first()
        siae2 = SiaeWith2MembershipsFactory()
        siae2.members.add(user)

        self.assertFalse(user in siae1.active_members)
        self.assertEqual(siae1.members.count(), 2)
        self.assertEqual(siae1.active_members.count(), 1)
        self.assertTrue(user in siae1.deactivated_members)
        self.assertFalse(user in siae1.active_members)
        self.assertEqual(siae2.members.count(), 3)
        self.assertEqual(siae2.active_members.count(), 3)

    def test_is_opcs(self):
        siae = SiaeFactory(kind=SiaeKind.ACI)
        self.assertFalse(siae.is_opcs)
        siae.kind = SiaeKind.OPCS
        self.assertTrue(siae.is_opcs)


class SiaeQuerySetTest(TestCase):
    def test_prefetch_job_description_through(self):
        siae = SiaeFactory(with_jobs=True)

        siae_result = Siae.objects.prefetch_job_description_through().get(pk=siae.pk)
        self.assertTrue(hasattr(siae_result, "job_description_through"))

        # by default every job description is active
        self.assertEqual(siae_result.job_description_through.count(), 4)

        first_job_description = siae_result.job_description_through.first()
        self.assertTrue(hasattr(first_job_description, "is_popular"))

        # now deactivate them
        jd = SiaeJobDescription.objects.filter(siae=siae).all()
        jd.update(is_active=False)
        siae_result = Siae.objects.prefetch_job_description_through().get(pk=siae.pk)
        self.assertEqual(siae_result.job_description_through.count(), 0)

    def test_with_count_recent_received_job_applications(self):
        siae = SiaeFactory()
        model = JobApplicationFactory._meta.model
        old_date = timezone.now() - timedelta(weeks=model.WEEKS_BEFORE_CONSIDERED_OLD, days=1)
        JobApplicationFactory(to_siae=siae, created_at=old_date)

        expected = 3
        for _ in range(expected):
            JobApplicationFactory(to_siae=siae)

        result = Siae.objects.with_count_recent_received_job_apps().get(pk=siae.pk)

        self.assertEqual(expected, result.count_recent_received_job_apps)

    def test_with_job_app_score(self):
        siae = SiaeFactory(with_jobs=True, romes=("N1101", "N1105", "N1103", "N4105"))
        siae.job_description_through.first()
        JobApplicationFactory(to_siae=siae)
        JobApplicationFactory(to_siae=siae)

        expected_score = siae.job_applications_received.count() / siae.job_description_through.count()
        result = Siae.objects.with_job_app_score().get(pk=siae.pk)

        active_job_descriptions = (
            Siae.objects.with_count_active_job_descriptions().get(pk=siae.pk).count_active_job_descriptions
        )
        self.assertEqual(active_job_descriptions, 4)
        recent_job_apps = (
            Siae.objects.with_count_recent_received_job_apps().get(pk=siae.pk).count_recent_received_job_apps
        )
        self.assertEqual(recent_job_apps, 2)
        self.assertEqual(expected_score, result.job_app_score)

    def test_with_job_app_score_no_job_description(self):
        siae = SiaeFactory()
        JobApplicationFactory(to_siae=siae)
        JobApplicationFactory(to_siae=siae)

        expected_score = None
        result = Siae.objects.with_job_app_score().get(pk=siae.pk)

        self.assertEqual(expected_score, result.job_app_score)

    def test_with_count_active_job_descriptions(self):
        siae = SiaeFactory(with_jobs=True, romes=("N1101", "N1105", "N1103", "N4105"))
        job_descriptions = siae.job_description_through.all()[:3]
        for job_description in job_descriptions:
            job_description.is_active = False
        SiaeJobDescription.objects.bulk_update(job_descriptions, ["is_active"])
        result = Siae.objects.with_count_active_job_descriptions().get(pk=siae.pk)

        self.assertEqual(1, result.count_active_job_descriptions)

    def test_with_has_active_members(self):
        siae = SiaeFactory(with_membership=True)
        result = Siae.objects.with_has_active_members().get(pk=siae.pk)
        self.assertTrue(result.has_active_members)

        # Deactivate members
        siae = Siae.objects.last()
        self.assertEqual(siae.members.count(), 1)
        membership = siae.siaemembership_set.first()
        membership.is_active = False
        membership.save()

        result = Siae.objects.with_has_active_members().get(pk=siae.pk)
        self.assertFalse(result.has_active_members)


class SiaeJobDescriptionQuerySetTest(TestCase):
    def setUp(self):
        self.siae = SiaeFactory(with_jobs=True)

    def test_with_annotation_is_popular(self):
        siae_job_descriptions = self.siae.job_description_through.all()

        # Test attribute presence
        siae_job_description = SiaeJobDescription.objects.with_annotation_is_popular().first()
        self.assertTrue(hasattr(siae_job_description, "is_popular"))

        # Test popular threshold: popular job description
        popular_job_description = siae_job_descriptions[0]
        for _ in range(SiaeJobDescription.POPULAR_THRESHOLD + 1):
            JobApplicationFactory(to_siae=self.siae, selected_jobs=[popular_job_description])

        self.assertTrue(
            SiaeJobDescription.objects.with_annotation_is_popular().get(pk=popular_job_description.pk).is_popular
        )

        # Test popular threshold: unpopular job description
        unpopular_job_description = siae_job_descriptions[1]
        JobApplicationFactory(to_siae=self.siae, selected_jobs=[unpopular_job_description])

        self.assertFalse(
            SiaeJobDescription.objects.with_annotation_is_popular().get(pk=unpopular_job_description.pk).is_popular
        )

        # Popular job descriptions count related **pending** job applications.
        # They should ignore other states.
        job_description = siae_job_descriptions[2]
        threshold_exceeded = SiaeJobDescription.POPULAR_THRESHOLD + 1

        JobApplicationFactory.create_batch(
            threshold_exceeded,
            to_siae=self.siae,
            selected_jobs=[popular_job_description],
            state=JobApplicationWorkflow.STATE_ACCEPTED,
        )

        self.assertFalse(SiaeJobDescription.objects.with_annotation_is_popular().get(pk=job_description.pk).is_popular)

    def test_with_job_applications_count(self):
        job_description = self.siae.job_description_through.first()
        JobApplicationFactory(to_siae=self.siae, selected_jobs=[job_description])
        siae_job_description = SiaeJobDescription.objects.with_job_applications_count().get(pk=job_description.pk)
        self.assertTrue(hasattr(siae_job_description, "job_applications_count"))
        self.assertEqual(siae_job_description.job_applications_count, 1)


class SiaeContractTypeTest(TestCase):
    def test_choices_for_siae(self):
        # Test only for GEIQ as the logic is the same for other Siae kind.
        expected = [
            ("APPRENTICESHIP", "Contrat d'apprentissage"),
            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
            ("OTHER", "Autre type de contrat"),
        ]
        result = ContractType.choices_for_siae(siae=SiaeFactory(kind=SiaeKind.GEIQ))
        self.assertEqual(result, expected)

        # For any ACI
        expected = [
            ("FIXED_TERM_I", "CDD insertion"),
            ("FIXED_TERM_USAGE", "CDD d'usage"),
            ("TEMPORARY", "Contrat de mission intérimaire"),
            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
            ("OTHER", "Autre type de contrat"),
        ]
        result = ContractType.choices_for_siae(siae=SiaeFactory(kind=SiaeKind.ACI))
        self.assertEqual(result, expected)

        # For an ACI from Convergence France
        expected = [
            ("FIXED_TERM_I", "CDD insertion"),
            ("FIXED_TERM_USAGE", "CDD d'usage"),
            ("TEMPORARY", "Contrat de mission intérimaire"),
            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
            ("FED_TERM_I_PHC", "CDD-I Premières heures en Chantier"),
            ("FIXED_TERM_I_CVG", "CDD-I Convergence"),
            ("OTHER", "Autre type de contrat"),
        ]
        siae = SiaeFactory(kind=SiaeKind.ACI)
        with override_settings(ACI_CONVERGENCE_PK_WHITELIST=[siae.pk]):
            result = ContractType.choices_for_siae(siae=siae)
        self.assertEqual(result, expected)

    def test_choices_for_siae_new_siae_kind(self):
        """
        A new SIAE kind has been added but it does not require specific contract types.
        This method should return all contracts except those for ACI from Convergence France.
        """
        expected = ContractType.choices

        expected.remove(("FED_TERM_I_PHC", "CDD-I Premières heures en Chantier"))
        expected.remove(("FIXED_TERM_I_CVG", "CDD-I Convergence"))
        result = ContractType.choices_for_siae(siae=SiaeFactory(kind="NEW"))
        self.assertEqual(result, expected)
