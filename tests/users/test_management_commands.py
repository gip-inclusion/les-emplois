import datetime
import json
import logging
from unittest import mock

import httpx
import pytest
from allauth.account import models as allauth_models
from allauth.account.models import EmailAddress
from dateutil.relativedelta import relativedelta
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.companies.enums import CompanyKind
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import IdentityCertificationAuthorities, IdentityProvider
from itou.users.management.commands import send_check_authorized_members_email
from itou.users.models import User
from itou.utils.apis.pole_emploi import PoleEmploiAPIBadResponse
from itou.utils.constants import BREVO_API_URL
from itou.utils.enums import BrevoListID
from itou.utils.mocks.pole_emploi import API_RECHERCHE_ERROR, API_RECHERCHE_RESULT_KNOWN
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.prescribers.factories import (
    PrescriberFactory,
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberPoleEmploiFactory,
)
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory


class TestDeduplicateJobSeekersManagementCommands:
    """
    Test the deduplication of several users.

    This is temporary and should be deleted after the release of the NIR
    which should prevent duplication.
    """

    def test_deduplicate_job_seekers(self):
        """
        Easy case : among all the duplicates, only one has a PASS IAE.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__jobseeker_profile__pole_emploi_id": "6666666B",
            "job_seeker__jobseeker_profile__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1`.
        job_app1 = JobApplicationFactory(with_approval=True, job_seeker__jobseeker_profile__nir="", **kwargs)
        user1 = job_app1.job_seeker

        assert user1.jobseeker_profile.nir == ""
        assert 1 == user1.approvals.count()
        assert 1 == user1.job_applications.count()
        assert 1 == user1.eligibility_diagnoses.count()

        # Create `user2`.
        job_app2 = JobApplicationFactory(job_seeker__jobseeker_profile__nir="", **kwargs)
        user2 = job_app2.job_seeker

        assert user2.jobseeker_profile.nir == ""
        assert 0 == user2.approvals.count()
        assert 1 == user2.job_applications.count()
        assert 1 == user2.eligibility_diagnoses.count()

        # Create `user3`.
        job_app3 = JobApplicationFactory(**kwargs)
        user3 = job_app3.job_seeker
        expected_nir = user3.jobseeker_profile.nir

        assert user3.jobseeker_profile.nir
        assert 0 == user3.approvals.count()
        assert 1 == user3.job_applications.count()
        assert 1 == user3.eligibility_diagnoses.count()

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_xlsx=True, wet_run=True)

        # If only one NIR exists for all the duplicates, it should
        # be reassigned to the target account.
        user1.refresh_from_db()
        assert user1.jobseeker_profile.nir == expected_nir

        assert 3 == user1.job_applications.count()
        assert 3 == user1.eligibility_diagnoses.count()
        assert 1 == user1.approvals.count()

        assert 0 == User.objects.filter(email=user2.email).count()
        assert 0 == User.objects.filter(email=user3.email).count()

        assert 0 == JobApplication.objects.filter(job_seeker=user2).count()
        assert 0 == JobApplication.objects.filter(job_seeker=user3).count()

        assert 0 == EligibilityDiagnosis.objects.filter(job_seeker=user2).count()
        assert 0 == EligibilityDiagnosis.objects.filter(job_seeker=user3).count()

    def test_deduplicate_job_seekers_without_empty_sender_field(self):
        """
        Easy case: among all the duplicates, only one has a PASS IAE.
        Ensure that the `sender` field is never left empty.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__jobseeker_profile__pole_emploi_id": "6666666B",
            "job_seeker__jobseeker_profile__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1` through a job application sent by him.
        job_app1 = JobApplicationSentByJobSeekerFactory(job_seeker__jobseeker_profile__nir="", **kwargs)
        user1 = job_app1.job_seeker

        assert 1 == user1.job_applications.count()
        assert job_app1.sender == user1

        # Create `user2` through a job application sent by him.
        job_app2 = JobApplicationSentByJobSeekerFactory(job_seeker__jobseeker_profile__nir="", **kwargs)
        user2 = job_app2.job_seeker

        assert 1 == user2.job_applications.count()
        assert job_app2.sender == user2

        # Create `user3` through a job application sent by a prescriber.
        job_app3 = JobApplicationFactory(job_seeker__jobseeker_profile__nir="", **kwargs)
        user3 = job_app3.job_seeker
        assert job_app3.sender != user3
        job_app3_sender = job_app3.sender  # The sender is a prescriber.

        # Ensure that `user1` will always be the target into which duplicates will be merged
        # by attaching a PASS IAE to him.
        assert 0 == user1.approvals.count()
        assert 0 == user2.approvals.count()
        assert 0 == user3.approvals.count()
        ApprovalFactory(user=user1)

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_xlsx=True, wet_run=True)

        assert 3 == user1.job_applications.count()

        job_app1.refresh_from_db()
        job_app2.refresh_from_db()
        job_app3.refresh_from_db()

        assert job_app1.sender == user1
        assert job_app2.sender == user1  # The sender must now be user1.
        assert job_app3.sender == job_app3_sender  # The sender must still be a prescriber.

        assert 0 == User.objects.filter(email=user2.email).count()
        assert 0 == User.objects.filter(email=user3.email).count()

        assert 0 == JobApplication.objects.filter(job_seeker=user2).count()
        assert 0 == JobApplication.objects.filter(job_seeker=user3).count()

        assert 0 == EligibilityDiagnosis.objects.filter(job_seeker=user2).count()
        assert 0 == EligibilityDiagnosis.objects.filter(job_seeker=user3).count()

    def test_hard_deduplicate_job_seekers(self):
        """
        Hard case : all the duplicates have their own Approval
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__jobseeker_profile__pole_emploi_id": "6666666B",
            "job_seeker__jobseeker_profile__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1`.
        job_app1 = JobApplicationFactory(with_approval=True, job_seeker__jobseeker_profile__nir="", **kwargs)
        user1 = job_app1.job_seeker

        # Create `user2` through a job application sent by him.
        job_app2 = JobApplicationSentByJobSeekerFactory(
            with_approval=True, job_seeker__jobseeker_profile__nir="", with_iae_eligibility_diagnosis=True, **kwargs
        )
        user2 = job_app2.job_seeker

        # Launch command
        call_command("deduplicate_job_seekers", verbosity=0, no_xlsx=True, wet_run=True)

        # It doesn't crash but users haven't been merged
        assertQuerySetEqual(
            JobApplication.objects.values_list("job_seeker_id", flat=True), [user1.pk, user2.pk], ordered=False
        )


@freeze_time("2023-03-06 11:40:01")
def test_shorten_active_sessions():
    expired_session = Session.objects.create(
        session_key="expired",
        expire_date=datetime.datetime(2023, 3, 6, tzinfo=datetime.UTC),
    )
    almost_expired_session = Session.objects.create(
        session_key="almost_expired",
        expire_date=datetime.datetime(2023, 3, 6, 12, tzinfo=datetime.UTC),
    )
    Session.objects.create(
        session_key="active",
        expire_date=datetime.datetime(2023, 3, 7, tzinfo=datetime.UTC),
    )

    call_command("shorten_active_sessions")
    assert list(Session.objects.all().order_by("expire_date").values_list("session_key", "expire_date")) == [
        ("expired", expired_session.expire_date),
        ("almost_expired", almost_expired_session.expire_date),
        ("active", timezone.now() + relativedelta(hours=1)),
    ]


class TestCommandSendUsersToBrevo:
    @pytest.fixture(autouse=True)
    def setup(self, settings):
        settings.BREVO_API_KEY = "BREVO_API_KEY"

    @freeze_time("2023-05-01T23:30:00Z")
    def test_wet_run_siae(self, caplog, respx_mock):
        for kind in set(CompanyKind) - set(CompanyKind.siae_kinds()):
            CompanyMembershipFactory(company__kind=kind, user__identity_provider=IdentityProvider.PRO_CONNECT)
        # Missing verified email and not using IC
        CompanyMembershipFactory(company__kind=CompanyKind.EI, user__identity_provider=IdentityProvider.DJANGO)
        not_primary = CompanyMembershipFactory(
            company__kind=CompanyKind.EI, user__identity_provider=IdentityProvider.DJANGO
        ).user
        EmailAddress.objects.create(user=not_primary, email=not_primary.email, primary=False, verified=True)
        # Inactive memberships are ignored.
        CompanyMembershipFactory(user__with_verified_email=True, company__kind=CompanyKind.EI, is_active=False)
        # Inactive users are ignored.
        CompanyMembershipFactory(user__with_verified_email=True, user__is_active=False, company__kind=CompanyKind.EI)
        # New email not verified is ignored when not using IC
        changed_email = CompanyMembershipFactory(
            user__with_verified_email=True,
            company__kind=CompanyKind.EI,
            user__identity_provider=IdentityProvider.DJANGO,
        ).user
        changed_email.email = "changed@mailinator.com"
        changed_email.save(update_fields=["email"])

        annie = EmployerFactory(
            first_name="Annie",
            last_name="Amma",
            email="annie.amma@mailinator.com",
            identity_provider=IdentityProvider.PRO_CONNECT,
        )
        bob = EmployerFactory(
            first_name="Bob",
            last_name="Bailey",
            email="bob.bailey@mailinator.com",
            identity_provider=IdentityProvider.PRO_CONNECT,
        )
        cindy = EmployerFactory(
            first_name="Cindy",
            last_name="Cinnamon",
            email="cindy.cinnamon@mailinator.com",
            identity_provider=IdentityProvider.PRO_CONNECT,
        )
        dave = EmployerFactory(
            first_name="Dave",
            last_name="Doll",
            email="dave.doll@mailinator.com",
            identity_provider=IdentityProvider.PRO_CONNECT,
        )
        eve = EmployerFactory(
            first_name="Eve",
            last_name="Ebi",
            email="eve.ebi@mailinator.com",
            identity_provider=IdentityProvider.PRO_CONNECT,
        )
        CompanyMembershipFactory(user=annie, company__kind=CompanyKind.EI)
        CompanyMembershipFactory(user=bob, company__kind=CompanyKind.AI)
        CompanyMembershipFactory(user=cindy, company__kind=CompanyKind.ACI)
        CompanyMembershipFactory(user=dave, company__kind=CompanyKind.ETTI)
        CompanyMembershipFactory(user=eve, company__kind=CompanyKind.EITI)

        import_mock = respx_mock.post(f"{BREVO_API_URL}/contacts/import").mock(
            return_value=httpx.Response(202, json={"processId": 106})
        )
        call_command("send_users_to_brevo", wet_run=True)

        assert [json.loads(call.request.content) for call in import_mock.calls] == [
            {
                "listIds": [BrevoListID.LES_EMPLOIS],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,
                "emptyContactsAttributes": False,
                "jsonBody": [
                    {
                        "email": "annie.amma@mailinator.com",
                        "attributes": {
                            "prenom": "Annie",
                            "nom": "AMMA",
                            "date_inscription": "2023-05-02",
                            "type": "employeur",
                        },
                    },
                    {
                        "email": "bob.bailey@mailinator.com",
                        "attributes": {
                            "prenom": "Bob",
                            "nom": "BAILEY",
                            "date_inscription": "2023-05-02",
                            "type": "employeur",
                        },
                    },
                    {
                        "email": "cindy.cinnamon@mailinator.com",
                        "attributes": {
                            "prenom": "Cindy",
                            "nom": "CINNAMON",
                            "date_inscription": "2023-05-02",
                            "type": "employeur",
                        },
                    },
                    {
                        "email": "dave.doll@mailinator.com",
                        "attributes": {
                            "prenom": "Dave",
                            "nom": "DOLL",
                            "date_inscription": "2023-05-02",
                            "type": "employeur",
                        },
                    },
                    {
                        "email": "eve.ebi@mailinator.com",
                        "attributes": {
                            "prenom": "Eve",
                            "nom": "EBI",
                            "date_inscription": "2023-05-02",
                            "type": "employeur",
                        },
                    },
                ],
            },
        ]
        assert caplog.record_tuples == [
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "SIAE users count: 5"),
            (
                "httpx",
                logging.INFO,
                'HTTP Request: POST https://api.brevo.com/v3/contacts/import "HTTP/1.1 202 Accepted"',
            ),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Orienteurs count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Job seekers count: 0"),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Stalled autonomous job seekers count: 0",
            ),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Management command itou.users.management.commands.send_users_to_brevo succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_prescribers(self, caplog, respx_mock):
        pe = PrescriberPoleEmploiFactory()
        other_org = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.ML, authorized=True)
        alice = PrescriberFactory(
            first_name="Alice",
            last_name="Aamar",
            email="alice.aamar@mailinator.com",
        )
        PrescriberMembershipFactory(user=alice, organization=pe)
        justin = PrescriberFactory(
            first_name="Justin",
            last_name="Wood",
            email="justin.wood@mailinator.com",
        )
        PrescriberMembershipFactory(user=justin, organization=other_org)

        for organization in [pe, other_org]:
            # Ignored, email is not the primary email.
            not_primary = PrescriberMembershipFactory(
                organization=organization, user__identity_provider=IdentityProvider.DJANGO
            ).user
            EmailAddress.objects.create(user=not_primary, email=not_primary.email, primary=False, verified=True)
            # Inactive users are ignored.
            PrescriberMembershipFactory(
                user__is_active=False, user__with_verified_email=True, organization=organization
            )
            # New email not verified is ignored when not using IC
            changed_email = PrescriberMembershipFactory(
                user__with_verified_email=True,
                organization=organization,
                user__identity_provider=IdentityProvider.DJANGO,
            ).user
            changed_email.email = f"changed+{organization}@mailinator.com"
            changed_email.save(update_fields=["email"])

        import_mock = respx_mock.post(f"{BREVO_API_URL}/contacts/import").mock(
            return_value=httpx.Response(202, json={"processId": 106})
        )

        call_command("send_users_to_brevo", wet_run=True)

        assert [json.loads(call.request.content) for call in import_mock.calls] == [
            {
                "listIds": [BrevoListID.LES_EMPLOIS],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,
                "emptyContactsAttributes": False,
                "jsonBody": [
                    {
                        "email": "alice.aamar@mailinator.com",
                        "attributes": {
                            "prenom": "Alice",
                            "nom": "AAMAR",
                            "date_inscription": "2023-05-02",
                            "type": "prescripteur habilité",
                        },
                    },
                    {
                        "email": "justin.wood@mailinator.com",
                        "attributes": {
                            "prenom": "Justin",
                            "nom": "WOOD",
                            "date_inscription": "2023-05-02",
                            "type": "prescripteur habilité",
                        },
                    },
                ],
            },
        ]
        assert caplog.record_tuples == [
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Prescribers count: 2"),
            (
                "httpx",
                logging.INFO,
                'HTTP Request: POST https://api.brevo.com/v3/contacts/import "HTTP/1.1 202 Accepted"',
            ),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Orienteurs count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Job seekers count: 0"),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Stalled autonomous job seekers count: 0",
            ),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Management command itou.users.management.commands.send_users_to_brevo succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_orienteurs(self, caplog, respx_mock):
        PrescriberFactory(
            first_name="Billy",
            last_name="Boo",
            email="billy.boo@mailinator.com",
        )
        sonny = PrescriberFactory(
            first_name="Sonny",
            last_name="Sunder",
            email="sonny.sunder@mailinator.com",
        )
        # Inactive memberships are considered orienteur.
        PrescriberMembershipFactory(user=sonny, is_active=False)
        # Members of unauthorized organizations are orienteurs.
        timmy = PrescriberFactory(
            first_name="Timmy",
            last_name="Timber",
            email="timmy.timber@mailinator.com",
        )
        PrescriberMembershipFactory(user=timmy, organization__kind=PrescriberOrganizationKind.OTHER)
        # Inactive users are ignored.
        PrescriberFactory(
            with_verified_email=True,
            is_active=False,
            date_joined=datetime.datetime(2023, 1, 12, tzinfo=datetime.UTC),
        )
        # Ignored, email is not the primary email when not using IC
        not_primary = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
        EmailAddress.objects.create(user=not_primary, email=not_primary.email, primary=False, verified=True)
        # New email not verified is ignored.
        changed_email = PrescriberFactory(with_verified_email=True, identity_provider=IdentityProvider.DJANGO)
        changed_email.email = "changed@mailinator.com"
        changed_email.save(update_fields=["email"])

        import_mock = respx_mock.post(f"{BREVO_API_URL}/contacts/import").mock(
            return_value=httpx.Response(202, json={"processId": 106})
        )

        call_command("send_users_to_brevo", wet_run=True)

        assert [json.loads(call.request.content) for call in import_mock.calls] == [
            {
                "listIds": [BrevoListID.LES_EMPLOIS],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,
                "emptyContactsAttributes": False,
                "jsonBody": [
                    {
                        "email": "billy.boo@mailinator.com",
                        "attributes": {
                            "prenom": "Billy",
                            "nom": "BOO",
                            "date_inscription": "2023-05-02",
                            "type": "orienteur",
                        },
                    },
                    {
                        "email": "sonny.sunder@mailinator.com",
                        "attributes": {
                            "prenom": "Sonny",
                            "nom": "SUNDER",
                            "date_inscription": "2023-05-02",
                            "type": "orienteur",
                        },
                    },
                    {
                        "email": "timmy.timber@mailinator.com",
                        "attributes": {
                            "prenom": "Timmy",
                            "nom": "TIMBER",
                            "date_inscription": "2023-05-02",
                            "type": "orienteur",
                        },
                    },
                ],
            },
        ]
        assert caplog.record_tuples == [
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Orienteurs count: 3"),
            (
                "httpx",
                logging.INFO,
                'HTTP Request: POST https://api.brevo.com/v3/contacts/import "HTTP/1.1 202 Accepted"',
            ),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Job seekers count: 0"),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Stalled autonomous job seekers count: 0",
            ),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Management command itou.users.management.commands.send_users_to_brevo succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2025-02-25")
    def test_wet_run_job_seekers(self, caplog, respx_mock):
        billy = JobSeekerFactory(
            first_name="Billy",
            last_name="Boo",
            email="billy.boo@mailinator.com",
            with_ban_geoloc_address=True,
            with_verified_email=True,
        )
        JobSeekerFactory(
            first_name="Sonny",
            last_name="Sunder",
            email="sonny.sunder@mailinator.com",
            date_joined=datetime.datetime(2025, 1, 25, tzinfo=timezone.get_current_timezone()),
            with_verified_email=True,
        )
        JobSeekerFactory(
            first_name="Timmy",
            last_name="Timber",
            email="timmy.timber@mailinator.com",
            is_active=False,
            with_verified_email=True,
        )
        valery = JobSeekerFactory(
            first_name="Valery",
            last_name="Vanda",
            email="valery.vanda@mailinator.com",
            identity_provider=IdentityProvider.PE_CONNECT,
            with_ban_geoloc_address=True,
        )
        not_primary = JobSeekerFactory()
        EmailAddress.objects.create(user=not_primary, email=not_primary.email, primary=False, verified=True)
        not_verified = JobSeekerFactory()
        allauth_models.EmailAddress.objects.create(
            user=not_verified,
            email="new@mailinator.com",
            primary=True,
            verified=False,
        )

        import_mock = respx_mock.post(f"{BREVO_API_URL}/contacts/import").mock(
            return_value=httpx.Response(202, json={"processId": 106})
        )

        call_command("send_users_to_brevo", wet_run=True)

        assert [json.loads(call.request.content) for call in import_mock.calls] == [
            {
                "listIds": [BrevoListID.CANDIDATS],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,
                "emptyContactsAttributes": False,
                "jsonBody": [
                    {
                        "email": "billy.boo@mailinator.com",
                        "attributes": {
                            "prenom": "Billy",
                            "nom": "BOO",
                            "date_inscription": "2025-02-25",
                            "departement": "67",
                            "id": billy.pk,
                        },
                    },
                    {
                        "email": "valery.vanda@mailinator.com",
                        "attributes": {
                            "prenom": "Valery",
                            "nom": "VANDA",
                            "date_inscription": "2025-02-25",
                            "departement": "67",
                            "id": valery.pk,
                        },
                    },
                ],
            },
        ]
        assert caplog.record_tuples == [
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Orienteurs count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Job seekers count: 2"),
            (
                "httpx",
                logging.INFO,
                'HTTP Request: POST https://api.brevo.com/v3/contacts/import "HTTP/1.1 202 Accepted"',
            ),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Stalled autonomous job seekers count: 0",
            ),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Management command itou.users.management.commands.send_users_to_brevo succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2025-02-25")
    def test_wet_run_stalled_autonomous_job_seekers(self, caplog, respx_mock):
        billy = JobSeekerFactory(
            first_name="Billy",
            last_name="Boo",
            email="billy.boo@mailinator.com",
            # Needed to fill the department field.
            with_ban_geoloc_address=True,
            with_verified_email=True,
        )
        JobApplicationFactory(
            job_seeker=billy,
            sender=billy,
            # More than six months ago, excluded by <6 months, matches >1 month.
            created_at=timezone.now() - datetime.timedelta(days=183),
            eligibility_diagnosis=None,
        )
        JobApplicationFactory(
            job_seeker=billy,
            sender=billy,
            # Less than 6 months ago.
            created_at=timezone.now() - datetime.timedelta(days=181),
            eligibility_diagnosis=None,
        )
        valery = JobSeekerFactory(
            first_name="Valery",
            last_name="Vanda",
            email="valery.vanda@mailinator.com",
            # Needed to fill the department field.
            with_ban_geoloc_address=True,
            with_verified_email=True,
        )
        valid_stalled_created_at = timezone.now() - datetime.timedelta(days=90)
        JobApplicationFactory(
            job_seeker=valery,
            sender=valery,
            # More than six months ago, excluded by <6 months, matches >1 month.
            created_at=valid_stalled_created_at,
            eligibility_diagnosis=None,
        )

        # The following job seekers are not sent.
        # Too recent.
        too_recent_job_seeker = JobSeekerFactory(first_name="recent", last_name="recent", with_verified_email=True)
        JobApplicationFactory(
            job_seeker=too_recent_job_seeker,
            sender=too_recent_job_seeker,
            eligibility_diagnosis=None,
        )
        # Too old.
        too_old_job_seeker = JobSeekerFactory(first_name="old", last_name="old", with_verified_email=True)
        JobApplicationFactory(
            created_at=timezone.now() - datetime.timedelta(days=185),
            job_seeker=too_old_job_seeker,
            sender=too_old_job_seeker,
            eligibility_diagnosis=None,
        )
        # Accepted
        accepted_job_seeker = JobSeekerFactory(first_name="accepted", last_name="accepted", with_verified_email=True)
        JobApplicationFactory(
            created_at=valid_stalled_created_at,
            state=JobApplicationState.ACCEPTED,
            job_seeker=accepted_job_seeker,
            sender=accepted_job_seeker,
            eligibility_diagnosis=None,
        )
        JobApplicationFactory(
            job_seeker=accepted_job_seeker,
            sender=accepted_job_seeker,
            eligibility_diagnosis=None,
        )
        # Has diagnosis.
        iae_job_seeker = JobSeekerFactory(first_name="iae_diag", last_name="iae_diag", with_verified_email=True)
        JobApplicationFactory(job_seeker=iae_job_seeker, sender=iae_job_seeker)
        JobApplicationFactory(job_seeker=iae_job_seeker, sender=iae_job_seeker, created_at=valid_stalled_created_at)
        geiq_job_seeker = JobSeekerFactory(first_name="geiq_diag", last_name="geiq_diag", with_verified_email=True)
        JobApplicationFactory(job_seeker=geiq_job_seeker, sender=geiq_job_seeker)
        JobApplicationFactory(job_seeker=geiq_job_seeker, sender=geiq_job_seeker, created_at=valid_stalled_created_at)
        # Has approval.
        approval_job_seeker = JobSeekerFactory(first_name="approval", last_name="approval", with_verified_email=True)
        approval = ApprovalFactory(user=approval_job_seeker)
        JobApplicationFactory(
            job_seeker=approval_job_seeker,
            sender=approval_job_seeker,
            approval=approval,
            eligibility_diagnosis=None,
        )
        JobApplicationFactory(
            job_seeker=approval_job_seeker,
            sender=approval_job_seeker,
            approval=approval,
            created_at=valid_stalled_created_at,
            eligibility_diagnosis=None,
        )
        import_mock = respx_mock.post(f"{BREVO_API_URL}/contacts/import").mock(
            return_value=httpx.Response(202, json={"processId": 106})
        )

        call_command("send_users_to_brevo", wet_run=True)

        # Employers and prescribers are created by the factories, ignore them.
        assert "Job seekers count: 8" in caplog.messages
        assert "Stalled autonomous job seekers count: 2" in caplog.messages
        autonomous_job_seeker_mock_call = import_mock.calls[-1]
        assert json.loads(autonomous_job_seeker_mock_call.request.content) == {
            "listIds": [BrevoListID.CANDIDATS_AUTONOMES_BLOQUES],
            "emailBlacklist": False,
            "smsBlacklist": False,
            "updateExistingContacts": False,
            "emptyContactsAttributes": False,
            "jsonBody": [
                {
                    "email": "billy.boo@mailinator.com",
                    "attributes": {
                        "prenom": "Billy",
                        "nom": "BOO",
                        "date_inscription": "2025-02-25",
                        "departement": "67",
                        "id": billy.pk,
                    },
                },
                {
                    "email": "valery.vanda@mailinator.com",
                    "attributes": {
                        "prenom": "Valery",
                        "nom": "VANDA",
                        "date_inscription": "2025-02-25",
                        "departement": "67",
                        "id": valery.pk,
                    },
                },
            ],
        }

    @freeze_time("2023-05-02")
    def test_wet_run_batch(self, caplog, respx_mock, mocker):
        annie = EmployerFactory(
            first_name="Annie",
            last_name="Amma",
            email="annie.amma@mailinator.com",
        )
        bob = EmployerFactory(
            first_name="Bob",
            last_name="Bailey",
            email="bob.bailey@mailinator.com",
        )
        CompanyMembershipFactory(user=annie, company__kind=CompanyKind.EI)
        CompanyMembershipFactory(user=bob, company__kind=CompanyKind.AI)

        import_mock = respx_mock.post(f"{BREVO_API_URL}/contacts/import").mock(
            return_value=httpx.Response(202, json={"processId": 106})
        )
        mocker.patch("itou.users.management.commands.send_users_to_brevo.BrevoClient.IMPORT_BATCH_SIZE", 1)

        call_command("send_users_to_brevo", wet_run=True)

        assert [json.loads(call.request.content) for call in import_mock.calls] == [
            {
                "listIds": [BrevoListID.LES_EMPLOIS],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,
                "emptyContactsAttributes": False,
                "jsonBody": [
                    {
                        "email": "annie.amma@mailinator.com",
                        "attributes": {
                            "prenom": "Annie",
                            "nom": "AMMA",
                            "date_inscription": "2023-05-02",
                            "type": "employeur",
                        },
                    },
                ],
            },
            {
                "listIds": [BrevoListID.LES_EMPLOIS],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,
                "emptyContactsAttributes": False,
                "jsonBody": [
                    {
                        "email": "bob.bailey@mailinator.com",
                        "attributes": {
                            "prenom": "Bob",
                            "nom": "BAILEY",
                            "date_inscription": "2023-05-02",
                            "type": "employeur",
                        },
                    },
                ],
            },
        ]
        assert caplog.record_tuples == [
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "SIAE users count: 2"),
            (
                "httpx",
                logging.INFO,
                'HTTP Request: POST https://api.brevo.com/v3/contacts/import "HTTP/1.1 202 Accepted"',
            ),
            (
                "httpx",
                logging.INFO,
                'HTTP Request: POST https://api.brevo.com/v3/contacts/import "HTTP/1.1 202 Accepted"',
            ),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Orienteurs count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Job seekers count: 0"),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Stalled autonomous job seekers count: 0",
            ),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Management command itou.users.management.commands.send_users_to_brevo succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_errors(self, caplog, respx_mock):
        annie = EmployerFactory(
            first_name="Annie",
            last_name="Amma",
            email="annie.amma@mailinator.com",
        )
        CompanyMembershipFactory(user=annie, company__kind=CompanyKind.EI)
        import_mock = respx_mock.post(f"{BREVO_API_URL}/contacts/import").mock(
            return_value=httpx.Response(400, json={})
        )

        call_command("send_users_to_brevo", wet_run=True)

        assert [json.loads(call.request.content) for call in import_mock.calls] == [
            {
                "listIds": [BrevoListID.LES_EMPLOIS],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,
                "emptyContactsAttributes": False,
                "jsonBody": [
                    {
                        "email": "annie.amma@mailinator.com",
                        "attributes": {
                            "prenom": "Annie",
                            "nom": "AMMA",
                            "date_inscription": "2023-05-02",
                            "type": "employeur",
                        },
                    },
                ],
            },
        ]
        assert caplog.record_tuples == [
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "SIAE users count: 1"),
            (
                "httpx",
                logging.INFO,
                'HTTP Request: POST https://api.brevo.com/v3/contacts/import "HTTP/1.1 400 Bad Request"',
            ),
            (
                "itou.utils.brevo",
                logging.ERROR,
                "Brevo API: Some emails were not imported, status_code=400, content={}",
            ),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Orienteurs count: 0"),
            ("itou.users.management.commands.send_users_to_brevo", logging.INFO, "Job seekers count: 0"),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Stalled autonomous job seekers count: 0",
            ),
            (
                "itou.users.management.commands.send_users_to_brevo",
                logging.INFO,
                "Management command itou.users.management.commands.send_users_to_brevo succeeded in 0.00 seconds",
            ),
        ]


@freeze_time("2023-05-01")
def test_update_job_seeker_coords(settings, capsys, respx_mock):
    js1 = JobSeekerFactory(
        with_address=True, coords="POINT (2.387311 48.917735)", geocoding_score=0.65
    )  # score too low
    js2 = JobSeekerFactory(with_address=True, coords=None, geocoding_score=0.9)  # no coords
    js3 = JobSeekerFactory(
        with_address=True, coords="POINT (5.43567 12.123876)", geocoding_score=0.76
    )  # score too low
    JobSeekerFactory(with_address_in_qpv=True)

    settings.API_BAN_BASE_URL = "https://geo.foo"
    respx_mock.post("https://geo.foo/search/csv/").respond(
        200,
        text=(
            "id;result_label;result_score;latitude;longitude\n"
            "42;7 rue de Laroche;0.77;42.42;13.13\n"  # score is lower than the minimum fiability score
            "12;5 rue Bigot;0.32;42.42;13.13\n"  # score is lower than the current one
            "78;9 avenue Delorme 92220 Boulogne;0.83;42.42;13.13\n"  # score is higher than current one
        ),
    )

    call_command("update_job_seeker_coords", wet_run=True, verbosity=2)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "> about to geolocate count=3 objects without geolocation or with a low score.",
        "> count=3 of these have an address and a post code.",
        "API result score=0.77 label='7 rue de Laroche' "
        f"searched_address='{js1.address_line_1} {js1.post_code}' object_pk={js1.id}",
        "API result score=0.32 label='5 rue Bigot' "
        f"searched_address='{js2.address_line_1} {js2.post_code}' object_pk={js2.id}",
        "API result score=0.83 label='9 avenue Delorme 92220 Boulogne' "
        f"searched_address='{js3.address_line_1} {js3.post_code}' object_pk={js3.id}",
        "> count=1 job seekers geolocated with a high score.",
    ]

    js3.refresh_from_db()
    assert js3.ban_api_resolved_address == "9 avenue Delorme 92220 Boulogne"
    assert js3.geocoding_updated_at == datetime.datetime(2023, 5, 1, 0, 0, tzinfo=datetime.UTC)
    assert js3.geocoding_score == 0.83
    assert js3.coords.x == 13.13
    assert js3.coords.y == 42.42


@freeze_time("2022-09-13")
def test_pe_certify_users(settings, respx_mock, caplog, snapshot):
    user = JobSeekerFactory(
        pk=424242,
        first_name="Yoder",
        last_name="Olson",
        jobseeker_profile__birthdate=datetime.date(1994, 2, 22),
        jobseeker_profile__nir="194022734304328",
    )
    settings.API_ESD = {
        "BASE_URL": "https://pe.fake",
        "AUTH_BASE_URL": "https://auth.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
    respx_mock.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
        200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
    )

    # user not found at all
    respx_mock.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
        200, json=API_RECHERCHE_ERROR
    )
    call_command("pe_certify_users", wet_run=True)
    assert caplog.messages[-1].startswith(
        "Management command itou.users.management.commands.pe_certify_users succeeded in "
    )
    assert caplog.messages[:-1] == snapshot()

    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 9, 13, 0, 0, tzinfo=datetime.UTC
    )
    assert user.jobseeker_profile.pe_obfuscated_nir is None

    # reset the jobseeker profile
    user.jobseeker_profile.pe_last_certification_attempt_at = None
    user.jobseeker_profile.save(update_fields=["pe_last_certification_attempt_at"])

    # user found immediately
    caplog.clear()
    respx_mock.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
        200, json=API_RECHERCHE_RESULT_KNOWN
    )
    call_command("pe_certify_users", wet_run=True)
    assert caplog.messages[-1].startswith(
        "Management command itou.users.management.commands.pe_certify_users succeeded in "
    )
    assert caplog.messages[:-1] == snapshot()

    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 9, 13, 0, 0, tzinfo=datetime.UTC
    )
    assert user.jobseeker_profile.pe_obfuscated_nir == "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"
    assertQuerySetEqual(
        user.jobseeker_profile.identity_certifications.all(),
        [IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE],
        transform=lambda certification: certification.certifier,
    )


@freeze_time("2022-09-13")
def test_pe_certify_users_with_swap(settings, respx_mock, caplog, snapshot):
    user = JobSeekerFactory(
        pk=424243,
        first_name="Balthazar",
        last_name="Durand",
        jobseeker_profile__birthdate=datetime.date(1987, 6, 21),
        jobseeker_profile__nir="187062112345678",
    )
    settings.API_ESD = {
        "BASE_URL": "https://pe.fake",
        "AUTH_BASE_URL": "https://auth.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
    respx_mock.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fpartenaire").respond(
        200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
    )
    respx_mock.post(
        "https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie",
        json={
            "dateNaissance": "1987-06-21",
            "nirCertifie": "1870621123456",
            "nomNaissance": "DURAND",
            "prenom": "BALTHAZAR",
        },
    ).respond(200, json=API_RECHERCHE_ERROR)
    respx_mock.post(
        "https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie",
        json={
            "dateNaissance": "1987-06-21",
            "nirCertifie": "1870621123456",
            "nomNaissance": "BALTHAZAR",
            "prenom": "DURAND",
        },
    ).respond(200, json=API_RECHERCHE_RESULT_KNOWN)
    call_command("pe_certify_users", wet_run=True)
    assert caplog.messages[-1].startswith(
        "Management command itou.users.management.commands.pe_certify_users succeeded in "
    )
    assert caplog.messages[:-1] == snapshot()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 9, 13, 0, 0, tzinfo=datetime.UTC
    )
    assert user.jobseeker_profile.pe_obfuscated_nir == "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"
    assertQuerySetEqual(
        user.jobseeker_profile.identity_certifications.all(),
        [IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE],
        transform=lambda certification: certification.certifier,
    )

    user.refresh_from_db()
    assert user.first_name == "Durand"
    assert user.last_name == "Balthazar"


def test_pe_certify_users_retry(caplog, snapshot):
    new_user = JobSeekerFactory(jobseeker_profile__pe_last_certification_attempt_at=None)
    old_failure = JobSeekerFactory(
        jobseeker_profile__pe_last_certification_attempt_at=timezone.now() - datetime.timedelta(days=90),
    )
    really_old_failure = JobSeekerFactory(
        jobseeker_profile__pe_last_certification_attempt_at=timezone.now() - datetime.timedelta(days=900),
    )
    JobSeekerFactory(
        jobseeker_profile__pe_last_certification_attempt_at=timezone.now() - datetime.timedelta(seconds=90),
    )  # recent failure that should not be called
    with mock.patch(
        "itou.utils.apis.PoleEmploiApiClient.recherche_individu_certifie", side_effect=PoleEmploiAPIBadResponse("R010")
    ) as recherche:
        call_command("pe_certify_users", wet_run=True)

    def recherche_call(user, swap):
        return mock.call(
            user.first_name if not swap else user.last_name,
            user.last_name if not swap else user.first_name,
            user.jobseeker_profile.birthdate,
            user.jobseeker_profile.nir,
        )

    assert recherche.mock_calls == [
        recherche_call(new_user, swap=False),
        recherche_call(new_user, swap=True),
        recherche_call(really_old_failure, swap=False),
        recherche_call(really_old_failure, swap=True),
        recherche_call(old_failure, swap=False),
        recherche_call(old_failure, swap=True),
    ]


class TestSendCheckAuthorizedMembersEmailManagementCommand:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        with freeze_time("2024-05-30"):
            self.employer_1 = CompanyMembershipFactory(user__email="employer1@test.local", company__name="Company 1")
            self.prescriber_1 = PrescriberMembershipFactory(
                organization__name="Organization 1",
                organization__created_at=timezone.now() - relativedelta(months=3),
            )
            self.labor_inspector_1 = InstitutionMembershipFactory(
                institution__name="Institution 1",
                institution__created_at=timezone.now() - relativedelta(months=3, days=-1),
            )

            yield

    @pytest.fixture(name="command")
    def command_fixture(self):
        return send_check_authorized_members_email.Command()

    def test_send_check_authorized_members_email_management_command_not_enough_members(
        self, django_capture_on_commit_callbacks, command, mailoutbox, caplog
    ):
        # Nothing to do (only one member per organization)
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert len(mailoutbox) == 0
        assert caplog.messages == [
            "Processing 0 companies",
            "Processing 0 prescriber organizations",
            "Processing 0 institutions",
        ]

    def test_send_check_authorized_members_email_management_command_created_at(
        self, django_capture_on_commit_callbacks, command, mailoutbox, caplog
    ):
        employer_2 = CompanyMembershipFactory(company=self.employer_1.company)
        prescriber_2 = PrescriberMembershipFactory(organization=self.prescriber_1.organization)
        labor_inspector_2 = InstitutionMembershipFactory(institution=self.labor_inspector_1.institution)

        # Should send 2 notifications to the 2 prescribers
        # Employer's company has been created today
        # Labor inspector's institution has been created less than 3 months ago
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert caplog.messages == [
            "Processing 0 companies",
            "Processing 1 prescriber organizations",
            f"Sent reminder notification to user {self.prescriber_1.user_id} "
            f"for prescriber organization {self.prescriber_1.organization_id}",
            f"Sent reminder notification to user {prescriber_2.user_id} "
            f"for prescriber organization {prescriber_2.organization_id}",
            "Processing 0 institutions",
        ]
        assert len(mailoutbox) == 2

        # Subsequent calls should not send other notifications
        caplog.clear()
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert caplog.messages == [
            "Processing 0 companies",
            "Processing 0 prescriber organizations",
            "Processing 0 institutions",
        ]
        assert len(mailoutbox) == 2

        # Update company and institution creation dates far in the past
        caplog.clear()
        self.employer_1.company.created_at -= relativedelta(months=5)
        self.employer_1.company.save(update_fields=["created_at", "updated_at"])
        self.labor_inspector_1.institution.created_at -= relativedelta(months=5)
        self.labor_inspector_1.institution.save(update_fields=["created_at", "updated_at"])
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert caplog.messages == [
            "Processing 1 companies",
            f"Sent reminder notification to user {self.employer_1.user_id} for company {self.employer_1.company_id}",
            f"Sent reminder notification to user {employer_2.user_id} for company {employer_2.company_id}",
            "Processing 0 prescriber organizations",
            "Processing 1 institutions",
            (
                f"Sent reminder notification to user {self.labor_inspector_1.user_id} "
                f"for institution {self.labor_inspector_1.institution_id}"
            ),
            (
                f"Sent reminder notification to user {labor_inspector_2.user_id} "
                f"for institution {labor_inspector_2.institution_id}"
            ),
        ]
        assert len(mailoutbox) == 6

    def test_send_check_authorized_members_email_management_command_active_members_email_reminder_last_sent_at(
        self, django_capture_on_commit_callbacks, command, mailoutbox, caplog
    ):
        employer_2 = CompanyMembershipFactory(company=self.employer_1.company)
        prescriber_2 = PrescriberMembershipFactory(organization=self.prescriber_1.organization)
        labor_inspector_2 = InstitutionMembershipFactory(institution=self.labor_inspector_1.institution)

        # Set created_at and active_members_email_reminder_last_sent_at
        NOW = timezone.now()
        self.employer_1.company.created_at = NOW - relativedelta(months=6)
        self.employer_1.company.active_members_email_reminder_last_sent_at = NOW - relativedelta(months=3)
        self.employer_1.company.save(
            update_fields=["created_at", "active_members_email_reminder_last_sent_at", "updated_at"]
        )
        self.prescriber_1.organization.created_at = NOW - relativedelta(months=6, days=-1)
        self.prescriber_1.organization.active_members_email_reminder_last_sent_at = NOW - relativedelta(
            months=3, days=-1
        )
        self.prescriber_1.organization.save(
            update_fields=["created_at", "active_members_email_reminder_last_sent_at", "updated_at"]
        )
        self.labor_inspector_1.institution.created_at = NOW - relativedelta(months=6, days=1)
        self.labor_inspector_1.institution.active_members_email_reminder_last_sent_at = NOW - relativedelta(
            months=3, days=1
        )
        self.labor_inspector_1.institution.save(
            update_fields=["created_at", "active_members_email_reminder_last_sent_at", "updated_at"]
        )

        # Should send 4 notifications to the 2 employers and the 2 labor inspectors
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert caplog.messages == [
            "Processing 1 companies",
            f"Sent reminder notification to user {self.employer_1.user_id} for company {self.employer_1.company_id}",
            f"Sent reminder notification to user {employer_2.user_id} for company {employer_2.company_id}",
            "Processing 0 prescriber organizations",
            "Processing 1 institutions",
            (
                f"Sent reminder notification to user {self.labor_inspector_1.user_id} "
                f"for institution {self.labor_inspector_1.institution_id}"
            ),
            (
                f"Sent reminder notification to user {labor_inspector_2.user_id} "
                f"for institution {labor_inspector_2.institution_id}"
            ),
        ]
        assert len(mailoutbox) == 4

        # Subsequent calls should not send other notifications
        caplog.clear()
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert caplog.messages == [
            "Processing 0 companies",
            "Processing 0 prescriber organizations",
            "Processing 0 institutions",
        ]
        assert len(mailoutbox) == 4

        # Update prescriber organization creation date enough in the past
        # Should not send any notification: only active_members_email_reminder_last_sent_at must be considered
        caplog.clear()
        self.prescriber_1.organization.created_at -= relativedelta(days=1)
        self.prescriber_1.organization.save(update_fields=["created_at", "updated_at"])
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert caplog.messages == [
            "Processing 0 companies",
            "Processing 0 prescriber organizations",
            "Processing 0 institutions",
        ]
        assert len(mailoutbox) == 4

        # Update prescriber organization last sent reminder date enough in the past
        # Should now send notification to prescribers
        caplog.clear()
        self.prescriber_1.organization.active_members_email_reminder_last_sent_at -= relativedelta(days=1)
        self.prescriber_1.organization.save(update_fields=["active_members_email_reminder_last_sent_at", "updated_at"])
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert caplog.messages == [
            "Processing 0 companies",
            "Processing 1 prescriber organizations",
            (
                f"Sent reminder notification to user {self.prescriber_1.user_id} "
                f"for prescriber organization {self.prescriber_1.organization_id}"
            ),
            (
                f"Sent reminder notification to user {prescriber_2.user_id} "
                f"for prescriber organization {prescriber_2.organization_id}"
            ),
            "Processing 0 institutions",
        ]
        assert len(mailoutbox) == 6

    def test_check_authorized_members_email_content_two_admins(
        self, django_capture_on_commit_callbacks, command, snapshot, mailoutbox
    ):
        PrescriberMembershipFactory(organization=self.prescriber_1.organization)

        # Should send 2 notifications to the 2 prescribers
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert len(mailoutbox) == 2
        assert (
            mailoutbox[0].subject
            == "[DEV] Rappel sécurité : vérifiez la liste des membres de l’organisation Organization 1"
        )
        assert mailoutbox[0].body == snapshot

    def test_check_authorized_members_email_content_one_admin(
        self, django_capture_on_commit_callbacks, command, snapshot, mailoutbox
    ):
        PrescriberMembershipFactory(organization=self.prescriber_1.organization, is_admin=False)

        # Should send 1 notification to the only one admin prescriber
        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert len(mailoutbox) == 1
        assert (
            mailoutbox[0].subject
            == "[DEV] Rappel sécurité : vérifiez la liste des membres de l’organisation Organization 1"
        )
        assert mailoutbox[0].body == snapshot

    def test_check_authorized_members_email_content_members_link(
        self, django_capture_on_commit_callbacks, command, snapshot, mailoutbox
    ):
        CompanyMembershipFactory(company=self.employer_1.company, is_admin=False)
        PrescriberMembershipFactory(organization=self.prescriber_1.organization, is_admin=False)
        InstitutionMembershipFactory(institution=self.labor_inspector_1.institution, is_admin=False)
        self.employer_1.company.created_at -= relativedelta(months=3)
        self.employer_1.company.save(update_fields=["created_at", "updated_at"])
        self.labor_inspector_1.institution.created_at -= relativedelta(days=1)
        self.labor_inspector_1.institution.save(update_fields=["created_at", "updated_at"])

        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert len(mailoutbox) == 3
        assert mailoutbox[0].body == snapshot(name="company")
        assert mailoutbox[1].body == snapshot(name="prescriber_organization")
        assert mailoutbox[2].body == snapshot(name="institution")

    def test_check_authorized_members_with_users_admins_of_multiple_organizations(
        self, django_capture_on_commit_callbacks, command, mailoutbox
    ):
        CompanyMembershipFactory(company=self.employer_1.company, is_admin=False)
        PrescriberMembershipFactory(organization=self.prescriber_1.organization, is_admin=False)
        InstitutionMembershipFactory(institution=self.labor_inspector_1.institution, is_admin=False)
        self.employer_1.company.created_at -= relativedelta(months=3)
        self.employer_1.company.save(update_fields=["created_at", "updated_at"])
        self.labor_inspector_1.institution.created_at -= relativedelta(days=1)
        self.labor_inspector_1.institution.save(update_fields=["created_at", "updated_at"])

        # Create other organizations with same users
        DT_3_MONTHS_AGO = timezone.now() - relativedelta(months=3)
        other_employer = CompanyMembershipFactory(
            user=self.employer_1.user, company__name="Company 2", company__created_at=DT_3_MONTHS_AGO
        )
        CompanyMembershipFactory(company=other_employer.company, is_admin=False)
        other_prescriber = PrescriberMembershipFactory(
            user=self.prescriber_1.user, organization__name="Organization 2", organization__created_at=DT_3_MONTHS_AGO
        )
        PrescriberMembershipFactory(organization=other_prescriber.organization, is_admin=False)
        other_labor_inspector = InstitutionMembershipFactory(
            user=self.labor_inspector_1.user,
            institution__name="Institution 2",
            institution__created_at=DT_3_MONTHS_AGO,
        )
        InstitutionMembershipFactory(institution=other_labor_inspector.institution, is_admin=False)

        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert len(mailoutbox) == 6
        expected_organization_names = [
            "Company 1",
            "Company 2",
            "Organization 1",
            "Organization 2",
            "Institution 1",
            "Institution 2",
        ]
        for idx, expected_organization_name in enumerate(expected_organization_names):
            assert mailoutbox[idx].subject == (
                f"[DEV] Rappel sécurité : vérifiez la liste des membres de l’organisation {expected_organization_name}"
            )

    def test_check_authorized_members_with_disabled_admin_companies(
        self, django_capture_on_commit_callbacks, command, mailoutbox
    ):
        self.employer_1.company.created_at -= relativedelta(months=3)
        self.employer_1.company.save(update_fields=["created_at", "updated_at"])

        # Create other company the user was once a member of
        DT_3_MONTHS_AGO = timezone.now() - relativedelta(months=3)
        company_2 = CompanyFactory(name="Company 2", created_at=DT_3_MONTHS_AGO)
        CompanyMembershipFactory(company=company_2, user=self.employer_1.user, is_admin=False, is_active=False)

        # Add an admin to both companies
        other_admin = EmployerFactory()
        admin_membership_1 = CompanyMembershipFactory(user=other_admin, company=self.employer_1.company)
        admin_membership_2 = CompanyMembershipFactory(user=other_admin, company=company_2)

        # Add another active user so that both companies have 2 or more active users
        other_active_member = EmployerFactory()
        CompanyMembershipFactory(user=other_active_member, company=self.employer_1.company, is_admin=False)
        CompanyMembershipFactory(user=other_active_member, company=company_2, is_admin=False)

        # an inactive user with active membership and admin (that's bad)
        inactive_admin = EmployerFactory(is_active=False)
        CompanyMembershipFactory(user=inactive_admin, company=self.employer_1.company)
        CompanyMembershipFactory(user=inactive_admin, company=company_2)

        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert len(mailoutbox) == 3
        expected_memberships = [self.employer_1, admin_membership_1, admin_membership_2]
        for idx, expected_membership in enumerate(expected_memberships):
            assert mailoutbox[idx].subject == (
                "[DEV] Rappel sécurité : "
                f"vérifiez la liste des membres de l’organisation {expected_membership.company.name}"
            )
            assert mailoutbox[idx].to == [expected_membership.user.email]

    def test_check_authorized_members_with_disabled_admin_organizations(
        self, django_capture_on_commit_callbacks, command, mailoutbox
    ):
        self.prescriber_1.organization.created_at -= relativedelta(months=3)
        self.prescriber_1.organization.save(update_fields=["created_at", "updated_at"])

        # Create other organization the user was once a member of
        DT_3_MONTHS_AGO = timezone.now() - relativedelta(months=3)
        organization_2 = PrescriberOrganizationFactory(name="Organization 2", created_at=DT_3_MONTHS_AGO)
        PrescriberMembershipFactory(
            organization=organization_2, user=self.prescriber_1.user, is_admin=False, is_active=False
        )

        # Add an admin to both organizations
        other_admin = PrescriberFactory()
        admin_membership_1 = PrescriberMembershipFactory(user=other_admin, organization=self.prescriber_1.organization)
        admin_membership_2 = PrescriberMembershipFactory(user=other_admin, organization=organization_2)

        # Add another active user so that both organizations have 2 or more active users
        other_active_member = PrescriberFactory()
        PrescriberMembershipFactory(
            user=other_active_member, organization=self.prescriber_1.organization, is_admin=False
        )
        PrescriberMembershipFactory(user=other_active_member, organization=organization_2, is_admin=False)

        # an inactive user with active membership and admin (that's bad)
        inactive_admin = PrescriberFactory(is_active=False)
        PrescriberMembershipFactory(user=inactive_admin, organization=self.prescriber_1.organization)
        PrescriberMembershipFactory(user=inactive_admin, organization=organization_2)

        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert len(mailoutbox) == 3
        expected_memberships = [self.prescriber_1, admin_membership_1, admin_membership_2]
        for idx, expected_membership in enumerate(expected_memberships):
            assert mailoutbox[idx].subject == (
                "[DEV] Rappel sécurité : "
                f"vérifiez la liste des membres de l’organisation {expected_membership.organization.name}"
            )
            assert mailoutbox[idx].to == [expected_membership.user.email]

    def test_check_authorized_members_with_disabled_admin_institution(
        self, django_capture_on_commit_callbacks, command, mailoutbox
    ):
        self.labor_inspector_1.institution.created_at -= relativedelta(months=3)
        self.labor_inspector_1.institution.save(update_fields=["created_at", "updated_at"])

        # Create other institution the user was once a member of
        DT_3_MONTHS_AGO = timezone.now() - relativedelta(months=3)
        institution_2 = InstitutionFactory(name="Institution 2", created_at=DT_3_MONTHS_AGO)
        InstitutionMembershipFactory(
            institution=institution_2, user=self.labor_inspector_1.user, is_admin=False, is_active=False
        )

        # Add an admin to both institutions
        other_admin = LaborInspectorFactory()
        admin_membership_1 = InstitutionMembershipFactory(
            user=other_admin, institution=self.labor_inspector_1.institution
        )
        admin_membership_2 = InstitutionMembershipFactory(user=other_admin, institution=institution_2)

        # Add another active user so that both institutions have 2 or more active users
        other_active_member = LaborInspectorFactory()
        InstitutionMembershipFactory(
            user=other_active_member, institution=self.labor_inspector_1.institution, is_admin=False
        )
        InstitutionMembershipFactory(user=other_active_member, institution=institution_2, is_admin=False)

        # an inactive user with active membership and admin (that's bad)
        inactive_admin = LaborInspectorFactory(is_active=False)
        InstitutionMembershipFactory(user=inactive_admin, institution=self.labor_inspector_1.institution)
        InstitutionMembershipFactory(user=inactive_admin, institution=institution_2)

        with django_capture_on_commit_callbacks(execute=True):
            command.handle()
        assert len(mailoutbox) == 3
        expected_memberships = [self.labor_inspector_1, admin_membership_1, admin_membership_2]
        for idx, expected_membership in enumerate(expected_memberships):
            assert mailoutbox[idx].subject == (
                "[DEV] Rappel sécurité : "
                f"vérifiez la liste des membres de l’organisation {expected_membership.institution.name}"
            )
            assert mailoutbox[idx].to == [expected_membership.user.email]
