from datetime import timedelta
from unittest import mock

import pytest
from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company, JobDescription
from itou.job_applications.models import JobApplicationWorkflow
from tests.companies.factories import (
    JobDescriptionFactory,
    SiaeAfterGracePeriodFactory,
    SiaeFactory,
    SiaePendingGracePeriodFactory,
    SiaeWith2MembershipsFactory,
    SiaeWith4MembershipsFactory,
    SiaeWithMembershipAndJobsFactory,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


class SiaeFactoriesTest(TestCase):
    def test_siae_with_membership_factory(self):
        siae = SiaeFactory(with_membership=True)
        assert siae.members.count() == 1
        user = siae.members.get()
        assert siae.has_admin(user)

    def test_siae_with_membership_and_jobs_factory(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        assert siae.jobs.count() == 2

    def test_siae_with_2_memberships_factory(self):
        siae = SiaeWith2MembershipsFactory()
        assert siae.members.count() == 2
        assert siae.active_members.count() == 2
        assert siae.active_admin_members.count() == 1
        admin_user = siae.active_admin_members.get()
        assert siae.has_admin(admin_user)
        all_users = list(siae.members.all())
        assert len(all_users) == 2
        all_users.remove(admin_user)
        assert len(all_users) == 1
        regular_user = all_users[0]
        assert not siae.has_admin(regular_user)

    def test_siae_with_4_memberships_factory(self):
        siae = SiaeWith4MembershipsFactory()
        assert siae.members.count() == 4
        assert siae.active_members.count() == 2
        assert siae.active_admin_members.count() == 1


class SiaeModelTest(TestCase):
    def test_accept_survey_url(self):
        siae = SiaeFactory(kind=CompanyKind.EI, department="57")
        url = siae.accept_survey_url
        assert url.startswith(f"{settings.TALLY_URL}/r/")
        assert f"id_siae={siae.pk}" in url
        assert "type_siae=Entreprise+d%27insertion" in url
        assert "region=Grand+Est" in url
        assert "departement=57" in url

        # Ensure that the URL does not break when there is no department.
        siae = SiaeFactory(kind=CompanyKind.AI, department="")
        assert url.startswith(f"{settings.TALLY_URL}/r/")
        url = siae.accept_survey_url
        assert f"id_siae={siae.pk}" in url
        assert "type_siae=Association+interm%C3%A9diaire" in url
        assert "region=" in url
        assert "departement=" in url

    def test_siren_and_nic(self):
        siae = SiaeFactory(siret="12345678900001")
        assert siae.siren == "123456789"
        assert siae.siret_nic == "00001"

    def test_is_subject_to_eligibility_rules(self):
        siae = SiaeFactory(kind=CompanyKind.GEIQ)
        assert not siae.is_subject_to_eligibility_rules

        siae = SiaeFactory(kind=CompanyKind.EI)
        assert siae.is_subject_to_eligibility_rules

    def test_should_have_convention(self):
        siae = SiaeFactory(kind=CompanyKind.GEIQ)
        assert not siae.should_have_convention

        siae = SiaeFactory(kind=CompanyKind.EI)
        assert siae.should_have_convention

    def test_has_members(self):
        siae1 = SiaeFactory()
        siae2 = SiaeFactory(with_membership=True)

        assert not siae1.has_members
        assert siae2.has_members

    def test_has_member(self):
        siae1 = SiaeFactory(with_membership=True)
        siae2 = SiaeFactory(with_membership=True)

        user1 = siae1.members.get()
        user2 = siae2.members.get()

        assert siae1.has_member(user1)
        assert not siae1.has_member(user2)

        assert siae2.has_member(user2)
        assert not siae2.has_member(user1)

    def test_active_members(self):
        siae = SiaeWith2MembershipsFactory(membership2__is_active=False)
        user_with_active_membership = siae.members.first()
        user_with_inactive_membership = siae.members.last()

        assert user_with_inactive_membership not in siae.active_members
        assert user_with_active_membership in siae.active_members

        # Deactivate a user
        user_with_active_membership.is_active = False
        user_with_active_membership.save()

        assert user_with_active_membership not in siae.active_members

    def test_active_admin_members(self):
        """
        Test that if a user is admin of siae_1 and regular user
        of siae_2 he is not considered as admin of siae_2.
        """
        siae_1 = SiaeFactory(with_membership=True)
        siae_1_admin_user = siae_1.members.first()
        siae_2 = SiaeFactory(with_membership=True)
        siae_2.members.add(siae_1_admin_user)

        assert siae_1_admin_user in siae_1.active_admin_members
        assert siae_1_admin_user not in siae_2.active_admin_members

    def test_has_admin(self):
        siae_1 = SiaeWith2MembershipsFactory()
        siae_1_admin_user = siae_1.active_admin_members.get()
        siae1_regular_user = siae_1.active_members.exclude(pk=siae_1_admin_user.pk).get()
        siae_2 = SiaeWith2MembershipsFactory(membership2__user=siae_1_admin_user)

        assert siae_1.has_member(siae_1_admin_user)
        assert siae_1.has_admin(siae_1_admin_user)

        assert siae_1.has_member(siae1_regular_user)
        assert not siae_1.has_admin(siae1_regular_user)

        assert siae_2.has_member(siae_1_admin_user)
        assert not siae_2.has_admin(siae_1_admin_user)

    def test_new_signup_activation_email_to_official_contact(self):
        siae = SiaeFactory(with_membership=True)
        token = siae.get_token()
        with mock.patch("itou.utils.tokens.SiaeSignupTokenGenerator.make_token", return_value=token):
            factory = RequestFactory()
            request = factory.get("/")

            message = siae.new_signup_activation_email_to_official_contact(request)
            message.send()

            assert len(mail.outbox) == 1
            email = mail.outbox[0]
            assert "Un nouvel utilisateur souhaite rejoindre votre structure" in email.subject
            assert "Ouvrez le lien suivant pour procéder à l'inscription" in email.body
            assert siae.signup_magic_link in email.body
            assert siae.display_name in email.body
            assert siae.siret in email.body
            assert siae.kind in email.body
            assert siae.auth_email in email.body
            assert siae.email not in email.body
            assert email.from_email == settings.DEFAULT_FROM_EMAIL
            assert len(email.to) == 1
            assert email.to[0] == siae.auth_email

    def test_activate_your_account_email(self):
        siae = SiaeFactory(with_membership=True)
        with pytest.raises(ValidationError):
            siae.activate_your_account_email()

        siae = SiaeFactory(auth_email="")
        with pytest.raises(ValidationError):
            siae.activate_your_account_email()

        siae = SiaeFactory()
        email = siae.activate_your_account_email()
        assert email.to == [siae.auth_email]
        assert siae.kind in email.subject
        assert siae.name in email.subject
        assert siae.kind in email.body
        assert siae.siret in email.body
        assert reverse("signup:siae_select") in email.body

    def test_deactivation_queryset_methods(self):
        siae = SiaeFactory()
        assert Company.objects.count() == 1
        assert Company.objects.active().count() == 1
        assert Company.objects.active_or_in_grace_period().count() == 1
        siae.delete()
        assert Company.objects.count() == 0

        siae = SiaePendingGracePeriodFactory()
        assert Company.objects.count() == 1
        assert Company.objects.active().count() == 0
        assert Company.objects.active_or_in_grace_period().count() == 1
        siae.delete()
        assert Company.objects.count() == 0

        siae = SiaeAfterGracePeriodFactory()
        assert Company.objects.count() == 1
        assert Company.objects.active().count() == 0
        assert Company.objects.active_or_in_grace_period().count() == 0
        siae.delete()
        assert Company.objects.count() == 0

    def test_active_member_with_many_memberships(self):
        siae1 = SiaeWith2MembershipsFactory(membership2__is_active=False)
        user = siae1.members.filter(companymembership__is_admin=False).first()
        siae2 = SiaeWith2MembershipsFactory()
        siae2.members.add(user)

        assert user not in siae1.active_members
        assert siae1.members.count() == 2
        assert siae1.active_members.count() == 1
        assert user in siae1.deactivated_members
        assert user not in siae1.active_members
        assert siae2.members.count() == 3
        assert siae2.active_members.count() == 3

    def test_is_opcs(self):
        siae = SiaeFactory(kind=CompanyKind.ACI)
        assert not siae.is_opcs
        siae.kind = CompanyKind.OPCS
        assert siae.is_opcs


class SiaeQuerySetTest(TestCase):
    def test_with_count_recent_received_job_applications(self):
        siae = SiaeFactory()
        model = JobApplicationFactory._meta.model
        old_date = timezone.now() - timedelta(weeks=model.WEEKS_BEFORE_CONSIDERED_OLD, days=1)
        JobApplicationFactory(to_siae=siae, created_at=old_date)

        expected = 3
        for _ in range(expected):
            JobApplicationFactory(to_siae=siae)

        result = Company.objects.with_count_recent_received_job_apps().get(pk=siae.pk)

        assert expected == result.count_recent_received_job_apps

    def test_with_computed_job_app_score(self):
        siae = SiaeFactory(with_jobs=True, romes=("N1101", "N1105", "N1103", "N4105"))
        siae.job_description_through.first()
        JobApplicationFactory(to_siae=siae)
        JobApplicationFactory(to_siae=siae)

        expected_score = siae.job_applications_received.count() / siae.job_description_through.count()
        result = Company.objects.with_computed_job_app_score().get(pk=siae.pk)

        active_job_descriptions = (
            Company.objects.with_count_active_job_descriptions().get(pk=siae.pk).count_active_job_descriptions
        )
        assert active_job_descriptions == 4
        recent_job_apps = (
            Company.objects.with_count_recent_received_job_apps().get(pk=siae.pk).count_recent_received_job_apps
        )
        assert recent_job_apps == 2
        assert expected_score == result.computed_job_app_score

    def test_with_computed_job_app_score_no_job_description(self):
        siae = SiaeFactory()
        JobApplicationFactory(to_siae=siae)
        JobApplicationFactory(to_siae=siae)

        expected_score = None
        result = Company.objects.with_computed_job_app_score().get(pk=siae.pk)

        assert expected_score == result.computed_job_app_score

    def test_with_count_active_job_descriptions(self):
        siae = SiaeFactory(with_jobs=True, romes=("N1101", "N1105", "N1103", "N4105"))
        job_descriptions = siae.job_description_through.all()[:3]
        for job_description in job_descriptions:
            job_description.is_active = False
        JobDescription.objects.bulk_update(job_descriptions, ["is_active"])
        result = Company.objects.with_count_active_job_descriptions().get(pk=siae.pk)

        assert 1 == result.count_active_job_descriptions

    def test_with_has_active_members(self):
        siae = SiaeFactory(with_membership=True)
        result = Company.objects.with_has_active_members().get(pk=siae.pk)
        assert result.has_active_members

        # Deactivate members
        siae = Company.objects.last()
        assert siae.members.count() == 1
        membership = siae.companymembership_set.first()
        membership.is_active = False
        membership.save()

        result = Company.objects.with_has_active_members().get(pk=siae.pk)
        assert not result.has_active_members

    def test_can_have_prior_action(self):
        siae = SiaeFactory()
        assert siae.can_have_prior_action is False
        geiq = SiaeFactory(kind=CompanyKind.GEIQ)
        assert geiq.can_have_prior_action is True


class JobDescriptionQuerySetTest(TestCase):
    def setUp(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        super().setUp()

    def test_with_annotation_is_popular(self):
        siae = SiaeFactory(with_jobs=True)
        job_seeker = JobSeekerFactory()  # We don't care if it's always the same
        siae_job_descriptions = siae.job_description_through.all()

        # Test attribute presence
        siae_job_description = JobDescription.objects.with_annotation_is_popular().first()
        assert hasattr(siae_job_description, "is_popular")

        # Test popular threshold: popular job description
        popular_job_description = siae_job_descriptions[0]
        for _ in range(JobDescription.POPULAR_THRESHOLD + 1):
            JobApplicationFactory(to_siae=siae, selected_jobs=[popular_job_description], job_seeker=job_seeker)

        assert JobDescription.objects.with_annotation_is_popular().get(pk=popular_job_description.pk).is_popular

        # Test popular threshold: unpopular job description
        unpopular_job_description = siae_job_descriptions[1]
        JobApplicationFactory(to_siae=siae, selected_jobs=[unpopular_job_description])

        assert not JobDescription.objects.with_annotation_is_popular().get(pk=unpopular_job_description.pk).is_popular

        # Popular job descriptions count related **pending** job applications.
        # They should ignore other states.
        job_description = siae_job_descriptions[2]
        threshold_exceeded = JobDescription.POPULAR_THRESHOLD + 1

        JobApplicationFactory.create_batch(
            threshold_exceeded,
            to_siae=siae,
            job_seeker=job_seeker,
            selected_jobs=[popular_job_description],
            state=JobApplicationWorkflow.STATE_ACCEPTED,
        )

        assert not JobDescription.objects.with_annotation_is_popular().get(pk=job_description.pk).is_popular

    def test_with_job_applications_count(self):
        siae = SiaeFactory(with_jobs=True)
        job_description = siae.job_description_through.first()
        JobApplicationFactory(to_siae=siae, selected_jobs=[job_description])
        siae_job_description = JobDescription.objects.with_job_applications_count().get(pk=job_description.pk)
        assert hasattr(siae_job_description, "job_applications_count")
        assert siae_job_description.job_applications_count == 1

    def test_is_active(self):
        siae = SiaeFactory(kind=CompanyKind.EI, convention=None)
        job = JobDescriptionFactory(siae=siae, is_active=False)
        assert JobDescription.objects.active().count() == 0
        job.is_active = True
        job.save(update_fields=["is_active"])
        assert JobDescription.objects.active().count() == 0
        siae.kind = CompanyKind.GEIQ
        siae.save(update_fields=["kind"])
        assert JobDescription.objects.active().count() == 1


class SiaeContractTypeTest(TestCase):
    def test_choices_for_siae(self):
        # Test only for GEIQ as the logic is the same for other Siae kind.
        expected = [
            ("APPRENTICESHIP", "Contrat d'apprentissage"),
            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
            ("OTHER", "Autre type de contrat"),
        ]
        result = ContractType.choices_for_siae(siae=SiaeFactory(kind=CompanyKind.GEIQ))
        assert result == expected

        # For any ACI
        expected = [
            ("FIXED_TERM_I", "CDD insertion"),
            ("FIXED_TERM_USAGE", "CDD d'usage"),
            ("TEMPORARY", "Contrat de mission intérimaire"),
            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
            ("OTHER", "Autre type de contrat"),
        ]
        result = ContractType.choices_for_siae(siae=SiaeFactory(kind=CompanyKind.ACI))
        assert result == expected

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
        siae = SiaeFactory(kind=CompanyKind.ACI)
        with override_settings(ACI_CONVERGENCE_SIRET_WHITELIST=[siae.siret]):
            result = ContractType.choices_for_siae(siae=siae)
        assert result == expected

    def test_choices_for_siae_new_siae_kind(self):
        """
        A new SIAE kind has been added but it does not require specific contract types.
        This method should return all contracts except those for ACI from Convergence France.
        """
        expected = ContractType.choices

        expected.remove(("FED_TERM_I_PHC", "CDD-I Premières heures en Chantier"))
        expected.remove(("FIXED_TERM_I_CVG", "CDD-I Convergence"))
        result = ContractType.choices_for_siae(siae=SiaeFactory(kind="NEW"))
        assert result == expected


@freeze_time("2020-06-21T08:29:34")
def test_jobdescription_is_active_field_history():
    create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
    job = JobDescriptionFactory(is_active=False)
    # trigger the first .from_db() call and populate _old_is_active.
    # please note that .refresh_from_db() would call .from_db() but _old_is_active
    # would not be populated since the instances in memory would be different.
    job = JobDescription.objects.get(pk=job.pk)
    assert job._old_is_active is False
    assert job.field_history == []

    # modify the field
    job.is_active = True
    job.save(update_fields=["is_active"])
    job = JobDescription.objects.get(pk=job.pk)
    assert job.field_history == [
        {
            "field": "is_active",
            "from": False,
            "to": True,
            "at": "2020-06-21T08:29:34Z",
        }
    ]

    # non-modifying "change"
    job.is_active = True
    job.save(update_fields=["is_active"])
    job = JobDescription.objects.get(pk=job.pk)
    assert job.field_history == [
        {
            "field": "is_active",
            "from": False,
            "to": True,
            "at": "2020-06-21T08:29:34Z",
        }
    ]

    # modify again
    job.is_active = False
    job.save()
    job = JobDescription.objects.get(pk=job.pk)
    assert job.field_history == [
        {
            "field": "is_active",
            "from": False,
            "to": True,
            "at": "2020-06-21T08:29:34Z",
        },
        {
            "field": "is_active",
            "from": True,
            "to": False,
            "at": "2020-06-21T08:29:34Z",
        },
    ]
