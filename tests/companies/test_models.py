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
from itou.job_applications.enums import JobApplicationState
from tests.companies.factories import (
    CompanyAfterGracePeriodFactory,
    CompanyFactory,
    CompanyMembershipFactory,
    CompanyPendingGracePeriodFactory,
    CompanyWith2MembershipsFactory,
    CompanyWith4MembershipsFactory,
    CompanyWithMembershipAndJobsFactory,
    JobDescriptionFactory,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


class CompanyFactoriesTest(TestCase):
    def test_company_with_membership_factory(self):
        company = CompanyFactory(with_membership=True)
        assert company.members.count() == 1
        user = company.members.get()
        assert company.has_admin(user)

    def test_siae_with_membership_and_jobs_factory(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        assert company.jobs.count() == 2

    def test_siae_with_2_memberships_factory(self):
        company = CompanyWith2MembershipsFactory()
        assert company.members.count() == 2
        assert company.active_members.count() == 2
        assert company.active_admin_members.count() == 1
        admin_user = company.active_admin_members.get()
        assert company.has_admin(admin_user)
        all_users = list(company.members.all())
        assert len(all_users) == 2
        all_users.remove(admin_user)
        assert len(all_users) == 1
        regular_user = all_users[0]
        assert not company.has_admin(regular_user)

    def test_siae_with_4_memberships_factory(self):
        company = CompanyWith4MembershipsFactory()
        assert company.members.count() == 4
        assert company.active_members.count() == 2
        assert company.active_admin_members.count() == 1


class SiaeModelTest(TestCase):
    def test_accept_survey_url(self):
        company = CompanyFactory(kind=CompanyKind.EI, department="57")
        url = company.accept_survey_url
        assert url.startswith(f"{settings.TALLY_URL}/r/")
        assert f"id_siae={company.pk}" in url
        assert "type_siae=Entreprise+d%27insertion" in url
        assert "region=Grand+Est" in url
        assert "departement=57" in url

        # Ensure that the URL does not break when there is no department.
        company = CompanyFactory(kind=CompanyKind.AI, department="")
        assert url.startswith(f"{settings.TALLY_URL}/r/")
        url = company.accept_survey_url
        assert f"id_siae={company.pk}" in url
        assert "type_siae=Association+interm%C3%A9diaire" in url
        assert "region=" in url
        assert "departement=" in url

    def test_siren_and_nic(self):
        company = CompanyFactory(siret="12345678900001")
        assert company.siren == "123456789"
        assert company.siret_nic == "00001"

    def test_is_subject_to_eligibility_rules(self):
        company = CompanyFactory(kind=CompanyKind.GEIQ)
        assert not company.is_subject_to_eligibility_rules

        company = CompanyFactory(kind=CompanyKind.EI)
        assert company.is_subject_to_eligibility_rules

    def test_should_have_convention(self):
        company = CompanyFactory(kind=CompanyKind.GEIQ)
        assert not company.should_have_convention

        company = CompanyFactory(kind=CompanyKind.EI)
        assert company.should_have_convention

    def test_has_members(self):
        company_1 = CompanyFactory()
        company_2 = CompanyFactory(with_membership=True)

        assert not company_1.has_members
        assert company_2.has_members

    def test_has_member(self):
        company_1 = CompanyFactory(with_membership=True)
        company_2 = CompanyFactory(with_membership=True)

        user1 = company_1.members.get()
        user2 = company_2.members.get()

        assert company_1.has_member(user1)
        assert not company_1.has_member(user2)

        assert company_2.has_member(user2)
        assert not company_2.has_member(user1)

    def test_active_members(self):
        company = CompanyWith2MembershipsFactory(membership2__is_active=False)
        active_user_with_active_membership = company.members.first()
        active_user_with_inactive_membership = company.members.last()
        inactive_user_with_active_membership = CompanyMembershipFactory(company=company, user__is_active=False)

        assert active_user_with_active_membership in company.active_members
        assert active_user_with_inactive_membership not in company.active_members
        assert inactive_user_with_active_membership not in company.active_members

        # Deactivate a membership
        active_user_with_active_membership.is_active = False
        active_user_with_active_membership.save()

        assert active_user_with_active_membership not in company.active_members

    def test_active_admin_members(self):
        """
        Test that if a user is admin of siae_1 and regular user
        of siae_2 he is not considered as admin of siae_2.
        """
        company_1 = CompanyFactory(with_membership=True)
        company_1_admin_user = company_1.members.first()
        company_2 = CompanyFactory(with_membership=True)
        company_2.members.add(company_1_admin_user)

        assert company_1_admin_user in company_1.active_admin_members
        assert company_1_admin_user not in company_2.active_admin_members

    def test_has_admin(self):
        company_1 = CompanyWith2MembershipsFactory()
        company_1_admin_user = company_1.active_admin_members.get()
        company_1_regular_user = company_1.active_members.exclude(pk=company_1_admin_user.pk).get()
        company_2 = CompanyWith2MembershipsFactory(membership2__user=company_1_admin_user)

        assert company_1.has_member(company_1_admin_user)
        assert company_1.has_admin(company_1_admin_user)

        assert company_1.has_member(company_1_regular_user)
        assert not company_1.has_admin(company_1_regular_user)

        assert company_2.has_member(company_1_admin_user)
        assert not company_2.has_admin(company_1_admin_user)

    def test_new_signup_activation_email_to_official_contact(self):
        company = CompanyFactory(with_membership=True)
        token = company.get_token()
        with mock.patch("itou.utils.tokens.CompanySignupTokenGenerator.make_token", return_value=token):
            factory = RequestFactory()
            request = factory.get("/")

            message = company.new_signup_activation_email_to_official_contact(request)
            with self.captureOnCommitCallbacks(execute=True):
                message.send()

            assert len(mail.outbox) == 1
            email = mail.outbox[0]
            assert "Un nouvel utilisateur souhaite rejoindre votre structure" in email.subject
            assert "Ouvrez le lien suivant pour procéder à l'inscription" in email.body
            assert company.signup_magic_link in email.body
            assert company.display_name in email.body
            assert company.siret in email.body
            assert company.kind in email.body
            assert company.auth_email in email.body
            assert company.email not in email.body
            assert email.from_email == settings.DEFAULT_FROM_EMAIL
            assert len(email.to) == 1
            assert email.to[0] == company.auth_email

    def test_activate_your_account_email(self):
        company = CompanyFactory(with_membership=True)
        with pytest.raises(ValidationError):
            company.activate_your_account_email()

        company = CompanyFactory(auth_email="")
        with pytest.raises(ValidationError):
            company.activate_your_account_email()

        company = CompanyFactory()
        email = company.activate_your_account_email()
        assert email.to == [company.auth_email]
        assert company.kind in email.subject
        assert company.name in email.subject
        assert company.kind in email.body
        assert company.siret in email.body
        assert reverse("signup:company_select") in email.body

    def test_deactivation_queryset_methods(self):
        company = CompanyFactory()
        assert Company.objects.count() == 1
        assert Company.objects.active().count() == 1
        assert Company.objects.active_or_in_grace_period().count() == 1
        company.delete()
        assert Company.objects.count() == 0

        company = CompanyPendingGracePeriodFactory()
        assert Company.objects.count() == 1
        assert Company.objects.active().count() == 0
        assert Company.objects.active_or_in_grace_period().count() == 1
        company.delete()
        assert Company.objects.count() == 0

        company = CompanyAfterGracePeriodFactory()
        assert Company.objects.count() == 1
        assert Company.objects.active().count() == 0
        assert Company.objects.active_or_in_grace_period().count() == 0
        company.delete()
        assert Company.objects.count() == 0

    def test_active_member_with_many_memberships(self):
        company_1 = CompanyWith2MembershipsFactory(membership2__is_active=False)
        user = company_1.members.filter(companymembership__is_admin=False).first()
        company_2 = CompanyWith2MembershipsFactory()
        company_2.members.add(user)

        assert user not in company_1.active_members
        assert company_1.members.count() == 2
        assert company_1.active_members.count() == 1
        assert user in company_1.deactivated_members
        assert user not in company_1.active_members
        assert company_2.members.count() == 3
        assert company_2.active_members.count() == 3

    def test_is_opcs(self):
        company = CompanyFactory(kind=CompanyKind.ACI)
        assert not company.is_opcs
        company.kind = CompanyKind.OPCS
        assert company.is_opcs


class SiaeQuerySetTest(TestCase):
    def test_with_count_recent_received_job_applications(self):
        company = CompanyFactory()
        model = JobApplicationFactory._meta.model
        old_date = timezone.now() - timedelta(weeks=model.WEEKS_BEFORE_CONSIDERED_OLD, days=1)
        JobApplicationFactory(to_company=company, created_at=old_date)

        expected = 3
        for _ in range(expected):
            JobApplicationFactory(to_company=company)

        result = Company.objects.with_count_recent_received_job_apps().get(pk=company.pk)

        assert expected == result.count_recent_received_job_apps

    def test_with_computed_job_app_score(self):
        company = CompanyFactory(with_jobs=True, romes=("N1101", "N1105", "N1103", "N4105"))
        company.job_description_through.first()
        JobApplicationFactory(to_company=company)
        JobApplicationFactory(to_company=company)

        expected_score = company.job_applications_received.count() / company.job_description_through.count()
        result = Company.objects.with_computed_job_app_score().get(pk=company.pk)

        active_job_descriptions = (
            Company.objects.with_count_active_job_descriptions().get(pk=company.pk).count_active_job_descriptions
        )
        assert active_job_descriptions == 4
        recent_job_apps = (
            Company.objects.with_count_recent_received_job_apps().get(pk=company.pk).count_recent_received_job_apps
        )
        assert recent_job_apps == 2
        assert expected_score == result.computed_job_app_score

    def test_with_computed_job_app_score_no_job_description(self):
        company = CompanyFactory()
        JobApplicationFactory(to_company=company)
        JobApplicationFactory(to_company=company)

        expected_score = None
        result = Company.objects.with_computed_job_app_score().get(pk=company.pk)

        assert expected_score == result.computed_job_app_score

    def test_with_count_active_job_descriptions(self):
        company = CompanyFactory(with_jobs=True, romes=("N1101", "N1105", "N1103", "N4105"))
        job_descriptions = company.job_description_through.all()[:3]
        for job_description in job_descriptions:
            job_description.is_active = False
        JobDescription.objects.bulk_update(job_descriptions, ["is_active"])
        result = Company.objects.with_count_active_job_descriptions().get(pk=company.pk)

        assert 1 == result.count_active_job_descriptions

    def test_with_has_active_members(self):
        company = CompanyFactory(with_membership=True)
        result = Company.objects.with_has_active_members().get(pk=company.pk)
        assert result.has_active_members

        # Deactivate members
        company = Company.objects.last()
        assert company.members.count() == 1
        membership = company.companymembership_set.first()
        membership.is_active = False
        membership.save()

        result = Company.objects.with_has_active_members().get(pk=company.pk)
        assert not result.has_active_members

    def test_can_have_prior_action(self):
        company = CompanyFactory()
        assert company.can_have_prior_action is False
        geiq = CompanyFactory(kind=CompanyKind.GEIQ)
        assert geiq.can_have_prior_action is True


class JobDescriptionQuerySetTest(TestCase):
    def setUp(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        super().setUp()

    def test_with_annotation_is_popular(self):
        company = CompanyFactory(with_jobs=True)
        job_seeker = JobSeekerFactory()  # We don't care if it's always the same
        siae_job_descriptions = company.job_description_through.all()

        # Test attribute presence
        siae_job_description = JobDescription.objects.with_annotation_is_popular().first()
        assert hasattr(siae_job_description, "is_popular")

        # Test popular threshold: popular job description
        popular_job_description = siae_job_descriptions[0]
        for _ in range(JobDescription.POPULAR_THRESHOLD + 1):
            JobApplicationFactory(to_company=company, selected_jobs=[popular_job_description], job_seeker=job_seeker)

        assert JobDescription.objects.with_annotation_is_popular().get(pk=popular_job_description.pk).is_popular

        # Test popular threshold: unpopular job description
        unpopular_job_description = siae_job_descriptions[1]
        JobApplicationFactory(to_company=company, selected_jobs=[unpopular_job_description])

        assert not JobDescription.objects.with_annotation_is_popular().get(pk=unpopular_job_description.pk).is_popular

        # Popular job descriptions count related **pending** job applications.
        # They should ignore other states.
        job_description = siae_job_descriptions[2]
        threshold_exceeded = JobDescription.POPULAR_THRESHOLD + 1

        JobApplicationFactory.create_batch(
            threshold_exceeded,
            to_company=company,
            job_seeker=job_seeker,
            selected_jobs=[popular_job_description],
            state=JobApplicationState.ACCEPTED,
        )

        assert not JobDescription.objects.with_annotation_is_popular().get(pk=job_description.pk).is_popular

    def test_with_job_applications_count(self):
        company = CompanyFactory(with_jobs=True)
        job_description = company.job_description_through.first()
        JobApplicationFactory(to_company=company, selected_jobs=[job_description])
        siae_job_description = JobDescription.objects.with_job_applications_count().get(pk=job_description.pk)
        assert hasattr(siae_job_description, "job_applications_count")
        assert siae_job_description.job_applications_count == 1

    def test_is_active(self):
        company = CompanyFactory(kind=CompanyKind.EI, convention=None)
        job = JobDescriptionFactory(company=company, is_active=False)
        assert JobDescription.objects.active().count() == 0
        job.is_active = True
        job.save(update_fields=["is_active"])
        assert JobDescription.objects.active().count() == 0
        company.kind = CompanyKind.GEIQ
        company.save(update_fields=["kind"])
        assert JobDescription.objects.active().count() == 1


class SiaeContractTypeTest(TestCase):
    def test_choices_for_siae(self):
        # Test only for GEIQ as the logic is the same for other Siae kind.
        expected = [
            ("APPRENTICESHIP", "Contrat d'apprentissage"),
            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
            ("OTHER", "Autre type de contrat"),
        ]
        result = ContractType.choices_for_company(company=CompanyFactory(kind=CompanyKind.GEIQ))
        assert result == expected

        # For any ACI
        expected = [
            ("FIXED_TERM_I", "CDD insertion"),
            ("FIXED_TERM_USAGE", "CDD d'usage"),
            ("TEMPORARY", "Contrat de mission intérimaire"),
            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
            ("OTHER", "Autre type de contrat"),
        ]
        result = ContractType.choices_for_company(company=CompanyFactory(kind=CompanyKind.ACI))
        assert result == expected

        # For an ACI from Convergence France
        expected = [
            ("FIXED_TERM_I", "CDD insertion"),
            ("FIXED_TERM_USAGE", "CDD d'usage"),
            ("TEMPORARY", "Contrat de mission intérimaire"),
            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
            ("FED_TERM_I_PHC", "CDD-I PHC"),
            ("FIXED_TERM_I_CVG", "CDD-I CVG"),
            ("OTHER", "Autre type de contrat"),
        ]
        company = CompanyFactory(kind=CompanyKind.ACI)
        with override_settings(ACI_CONVERGENCE_SIRET_WHITELIST=[company.siret]):
            result = ContractType.choices_for_company(company=company)
        assert result == expected

    def test_choices_for_siae_new_siae_kind(self):
        """
        A new SIAE kind has been added but it does not require specific contract types.
        This method should return all contracts except those for ACI from Convergence France.
        """
        expected = ContractType.choices

        expected.remove(("FED_TERM_I_PHC", "CDD-I PHC"))
        expected.remove(("FIXED_TERM_I_CVG", "CDD-I CVG"))
        result = ContractType.choices_for_company(company=CompanyFactory(kind="NEW"))
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
