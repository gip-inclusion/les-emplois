import datetime
import io
import json
import logging
from unittest import mock

import httpx
from allauth.account.models import EmailAddress
from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time

from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS, CompanyKind
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import IdentityProvider, UserKind
from itou.users.management.commands.new_users_to_mailjet import (
    MAILJET_API_URL,
    NEW_ORIENTEURS_LISTID,
    NEW_PE_LISTID,
    NEW_PRESCRIBERS_LISTID,
    NEW_SIAE_LISTID,
)
from itou.users.models import User
from itou.utils.apis.pole_emploi import (
    PoleEmploiAPIBadResponse,
)
from itou.utils.mocks.pole_emploi import API_RECHERCHE_ERROR, API_RECHERCHE_RESULT_KNOWN
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyMembershipFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.prescribers.factories import (
    PrescriberFactory,
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberPoleEmploiFactory,
)
from tests.users.factories import EmployerFactory, JobSeekerFactory, JobSeekerWithAddressFactory
from tests.utils.test import TestCase


class DeduplicateJobSeekersManagementCommandsTest(TestCase):
    """
    Test the deduplication of several users.

    This is temporary and should be deleted after the release of the NIR
    which should prevent duplication.
    """

    def test_deduplicate_job_seekers(self):
        """
        Easy case : among all the duplicates, only one has a PASS IAE.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__jobseeker_profile__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
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
        Easy case: among all the duplicates, only one has a PASS IAE.
        Ensure that the `sender` field is never left empty.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__jobseeker_profile__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
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
        # by attaching a PASS IAE to him.
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
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1`.
        job_app1 = JobApplicationFactory(with_approval=True, job_seeker__jobseeker_profile__nir="", **kwargs)
        user1 = job_app1.job_seeker

        # Create `user2` through a job application sent by him.
        job_app2 = JobApplicationSentByJobSeekerFactory(
            with_approval=True, job_seeker__jobseeker_profile__nir="", **kwargs
        )
        user2 = job_app2.job_seeker

        # Launch command
        call_command("deduplicate_job_seekers", verbosity=0, no_xlsx=True, wet_run=True)

        # It doesn't crash but users haven't been merged
        self.assertQuerySetEqual(
            JobApplication.objects.values_list("job_seeker_id", flat=True), [user1.pk, user2.pk], ordered=False
        )


class TestSyncPermsTestCase(TestCase):
    def test_sync_perms(self):
        stdout = io.StringIO()
        call_command("sync_group_and_perms", stdout=stdout)
        stdout.seek(0)
        output = stdout.readlines()
        assert output == [
            "group name=itou-admin created\n",
            "group name=itou-support-externe created\n",
            "All done!\n",
        ]
        assert Group.objects.all().count() == 2
        admin_group = Group.objects.get(name="itou-admin")
        assert [perm.codename for perm in admin_group.permissions.all()] == [
            "add_emailaddress",
            "change_emailaddress",
            "view_emailaddress",
            "view_datum",
            "view_statsdashboardvisit",
            "add_approval",
            "change_approval",
            "delete_approval",
            "view_approval",
            "view_cancelledapproval",
            "view_poleemploiapproval",
            "add_prolongation",
            "change_prolongation",
            "delete_prolongation",
            "view_prolongation",
            "add_suspension",
            "change_suspension",
            "delete_suspension",
            "view_suspension",
            "view_commune",
            "view_country",
            "view_department",
            "view_city",
            "add_company",
            "change_company",
            "view_company",
            "add_companymembership",
            "change_companymembership",
            "delete_companymembership",
            "view_companymembership",
            "add_jobdescription",
            "change_jobdescription",
            "delete_jobdescription",
            "view_jobdescription",
            "change_siaeconvention",
            "view_siaeconvention",
            "view_siaefinancialannex",
            "view_administrativecriteria",
            "add_eligibilitydiagnosis",
            "change_eligibilitydiagnosis",
            "view_eligibilitydiagnosis",
            "add_selectedadministrativecriteria",
            "change_selectedadministrativecriteria",
            "delete_selectedadministrativecriteria",
            "view_selectedadministrativecriteria",
            "change_employeerecord",
            "delete_employeerecord",
            "view_employeerecord",
            "add_institution",
            "change_institution",
            "view_institution",
            "add_institutionmembership",
            "change_institutionmembership",
            "delete_institutionmembership",
            "view_institutionmembership",
            "change_employerinvitation",
            "delete_employerinvitation",
            "view_employerinvitation",
            "change_laborinspectorinvitation",
            "delete_laborinspectorinvitation",
            "view_laborinspectorinvitation",
            "change_prescriberwithorginvitation",
            "delete_prescriberwithorginvitation",
            "view_prescriberwithorginvitation",
            "change_jobapplication",
            "delete_jobapplication",
            "view_jobapplication",
            "view_jobapplicationtransitionlog",
            "view_appellation",
            "view_rome",
            "add_prescribermembership",
            "change_prescribermembership",
            "delete_prescribermembership",
            "view_prescribermembership",
            "add_prescriberorganization",
            "change_prescriberorganization",
            "view_prescriberorganization",
            "view_calendar",
            "view_evaluatedadministrativecriteria",
            "view_evaluatedjobapplication",
            "view_evaluatedsiae",
            "view_evaluationcampaign",
            "view_sanctions",
            "change_jobseekerprofile",
            "view_jobseekerprofile",
            "add_user",
            "change_user",
            "view_user",
        ]
        support_group = Group.objects.get(name="itou-support-externe")
        assert [perm.codename for perm in support_group.permissions.all()] == [
            "view_emailaddress",
            "view_approval",
            "view_cancelledapproval",
            "view_poleemploiapproval",
            "view_prolongation",
            "view_suspension",
            "view_commune",
            "view_country",
            "view_department",
            "view_city",
            "view_company",
            "view_companymembership",
            "view_jobdescription",
            "view_siaeconvention",
            "view_siaefinancialannex",
            "view_administrativecriteria",
            "view_eligibilitydiagnosis",
            "view_selectedadministrativecriteria",
            "view_employeerecord",
            "view_institution",
            "view_institutionmembership",
            "view_employerinvitation",
            "view_laborinspectorinvitation",
            "view_prescriberwithorginvitation",
            "view_jobapplication",
            "view_jobapplicationtransitionlog",
            "view_appellation",
            "view_rome",
            "view_prescribermembership",
            "view_prescriberorganization",
            "view_jobseekerprofile",
            "view_user",
        ]


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


class TestCommandNewUsersToMailJet:
    @freeze_time("2023-05-02")
    def test_wet_run_siae(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

        # Job seekers are ignored.
        JobSeekerFactory(with_verified_email=True)
        for kind in set(CompanyKind) - set(SIAE_WITH_CONVENTION_KINDS):
            CompanyMembershipFactory(company__kind=kind, user__identity_provider=IdentityProvider.INCLUSION_CONNECT)
        # Missing verified email and not using IC
        CompanyMembershipFactory(company__kind=CompanyKind.EI, user__identity_provider=IdentityProvider.DJANGO)
        not_primary = CompanyMembershipFactory(
            company__kind=CompanyKind.EI, user__identity_provider=IdentityProvider.DJANGO
        ).user
        EmailAddress.objects.create(user=not_primary, email=not_primary.email, primary=False, verified=True)
        # Past users are ignored.
        CompanyMembershipFactory(
            user__date_joined=datetime.datetime(2023, 1, 12, tzinfo=datetime.UTC),
            user__with_verified_email=True,
            company__kind=CompanyKind.EI,
        )
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
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        bob = EmployerFactory(
            first_name="Bob",
            last_name="Bailey",
            email="bob.bailey@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        cindy = EmployerFactory(
            first_name="Cindy",
            last_name="Cinnamon",
            email="cindy.cinnamon@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        dave = EmployerFactory(
            first_name="Dave",
            last_name="Doll",
            email="dave.doll@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        eve = EmployerFactory(
            first_name="Eve",
            last_name="Ebi",
            email="eve.ebi@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        CompanyMembershipFactory(user=annie, company__kind=CompanyKind.EI)
        CompanyMembershipFactory(user=bob, company__kind=CompanyKind.AI)
        CompanyMembershipFactory(user=cindy, company__kind=CompanyKind.ACI)
        CompanyMembershipFactory(user=dave, company__kind=CompanyKind.ETTI)
        CompanyMembershipFactory(user=eve, company__kind=CompanyKind.EITI)
        post_mock = respx_mock.post(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts").mock(
            return_value=httpx.Response(201, json={"Count": 1, "Data": [{"JobID": 123456789}], "Total": 1})
        )
        respx_mock.get(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/123456789").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "Count": 1,
                        "Data": [
                            {
                                "ContactsLists": [{"ListID": NEW_SIAE_LISTID, "Action": "addnoforce"}],
                                "Count": 2,
                                "Error": "",
                                "ErrorFile": "",
                                "JobStart": "2023-05-02T11:11:11",
                                "JobEnd": "",
                                "Status": "In Progress",
                            }
                        ],
                        "Total": 1,
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "Count": 1,
                        "Data": [
                            {
                                "ContactsLists": [{"ListID": NEW_SIAE_LISTID, "Action": "addnoforce"}],
                                "Count": 5,
                                "Error": "",
                                "ErrorFile": "",
                                "JobStart": "2023-05-02T11:11:11",
                                "JobEnd": "2023-05-02T12:34:56",
                                "Status": "Completed",
                            }
                        ],
                        "Total": 1,
                    },
                ),
            ]
        )
        with mock.patch("itou.users.management.commands.new_users_to_mailjet.time.sleep") as time_mock:
            call_command("new_users_to_mailjet", wet_run=True)
            time_mock.assert_called_once_with(2)
        [postcall] = post_mock.calls

        assert json.loads(postcall.request.content) == {
            "Action": "addnoforce",
            "Contacts": [
                {"Email": "annie.amma@mailinator.com", "Name": "Annie AMMA"},
                {"Email": "bob.bailey@mailinator.com", "Name": "Bob BAILEY"},
                {"Email": "cindy.cinnamon@mailinator.com", "Name": "Cindy CINNAMON"},
                {"Email": "dave.doll@mailinator.com", "Name": "Dave DOLL"},
                {"Email": "eve.ebi@mailinator.com", "Name": "Eve EBI"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 5"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: POST https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts "HTTP/1.1 201 Created"',  # noqa: E501
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: GET https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/123456789 "HTTP/1.1 200 OK"',  # noqa: E501
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: GET https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/123456789 "HTTP/1.1 200 OK"',  # noqa: E501
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_SIAE_LISTID} in 5025 seconds.",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                "Management command itou.users.management.commands.new_users_to_mailjet succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_prescribers(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

        pe = PrescriberPoleEmploiFactory()
        other_org = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.ML, authorized=True)
        alice = PrescriberFactory(
            first_name="Alice",
            last_name="Aamar",
            email="alice.aamar@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        PrescriberMembershipFactory(user=alice, organization=pe)
        justin = PrescriberFactory(
            first_name="Justin",
            last_name="Wood",
            email="justin.wood@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        PrescriberMembershipFactory(user=justin, organization=other_org)

        for organization in [pe, other_org]:
            # Ignored, email is not the primary email.
            not_primary = PrescriberMembershipFactory(
                organization=organization, user__identity_provider=IdentityProvider.DJANGO
            ).user
            EmailAddress.objects.create(user=not_primary, email=not_primary.email, primary=False, verified=True)
            # Past users are ignored.
            PrescriberMembershipFactory(
                user__date_joined=datetime.datetime(2023, 1, 12, tzinfo=datetime.UTC),
                user__with_verified_email=True,
                organization=organization,
            )
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

        pe_post_mock = respx_mock.post(f"{MAILJET_API_URL}REST/contactslist/{NEW_PE_LISTID}/managemanycontacts").mock(
            return_value=httpx.Response(201, json={"Count": 1, "Data": [{"JobID": 123456789}], "Total": 1})
        )
        respx_mock.get(f"{MAILJET_API_URL}REST/contactslist/{NEW_PE_LISTID}/managemanycontacts/123456789").mock(
            return_value=httpx.Response(
                200,
                json={
                    "Count": 1,
                    "Data": [
                        {
                            "ContactsLists": [{"ListID": NEW_PE_LISTID, "Action": "addnoforce"}],
                            "Count": 1,
                            "Error": "",
                            "ErrorFile": "",
                            "JobStart": "2023-05-02T11:11:11",
                            "JobEnd": "2023-05-02T11:11:56",
                            "Status": "Completed",
                        }
                    ],
                    "Total": 1,
                },
            ),
        )
        other_org_post_mock = respx_mock.post(
            f"{MAILJET_API_URL}REST/contactslist/{NEW_PRESCRIBERS_LISTID}/managemanycontacts"
        ).mock(return_value=httpx.Response(201, json={"Count": 1, "Data": [{"JobID": 123456789}], "Total": 1}))
        respx_mock.get(
            f"{MAILJET_API_URL}REST/contactslist/{NEW_PRESCRIBERS_LISTID}/managemanycontacts/123456789"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "Count": 1,
                    "Data": [
                        {
                            "ContactsLists": [{"ListID": NEW_PRESCRIBERS_LISTID, "Action": "addnoforce"}],
                            "Count": 1,
                            "Error": "",
                            "ErrorFile": "",
                            "JobStart": "2023-05-02T11:11:11",
                            "JobEnd": "2023-05-02T11:11:56",
                            "Status": "Completed",
                        }
                    ],
                    "Total": 1,
                },
            ),
        )
        call_command("new_users_to_mailjet", wet_run=True)
        [pe_postcall] = pe_post_mock.calls
        assert json.loads(pe_postcall.request.content) == {
            "Action": "addnoforce",
            "Contacts": [{"Email": "alice.aamar@mailinator.com", "Name": "Alice AAMAR"}],
        }
        [other_org_postcall] = other_org_post_mock.calls
        assert json.loads(other_org_postcall.request.content) == {
            "Action": "addnoforce",
            "Contacts": [
                {"Email": "alice.aamar@mailinator.com", "Name": "Alice AAMAR"},
                {"Email": "justin.wood@mailinator.com", "Name": "Justin WOOD"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 1"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 2"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: POST https://api.mailjet.com/v3/REST/contactslist/{NEW_PE_LISTID}/managemanycontacts "HTTP/1.1 201 Created"',  # noqa: E501
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: GET https://api.mailjet.com/v3/REST/contactslist/{NEW_PE_LISTID}/managemanycontacts/123456789 "HTTP/1.1 200 OK"',  # noqa: E501
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_PE_LISTID} in 45 seconds.",
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: POST https://api.mailjet.com/v3/REST/contactslist/{NEW_PRESCRIBERS_LISTID}/managemanycontacts "HTTP/1.1 201 Created"',  # noqa: E501
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: GET https://api.mailjet.com/v3/REST/contactslist/{NEW_PRESCRIBERS_LISTID}/managemanycontacts/123456789 "HTTP/1.1 200 OK"',  # noqa: E501
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_PRESCRIBERS_LISTID} in 45 seconds.",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                "Management command itou.users.management.commands.new_users_to_mailjet succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_orienteurs(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

        PrescriberFactory(
            first_name="Billy",
            last_name="Boo",
            email="billy.boo@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        sonny = PrescriberFactory(
            first_name="Sonny",
            last_name="Sunder",
            email="sonny.sunder@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        # Inactive memberships are considered orienteur.
        PrescriberMembershipFactory(user=sonny, is_active=False)
        # Members of unauthorized organizations are orienteurs.
        timmy = PrescriberFactory(
            first_name="Timmy",
            last_name="Timber",
            email="timmy.timber@mailinator.com",
            identity_provider=IdentityProvider.INCLUSION_CONNECT,
        )
        PrescriberMembershipFactory(user=timmy, organization__kind=PrescriberOrganizationKind.OTHER)
        # Past users are ignored.
        PrescriberFactory(with_verified_email=True, date_joined=datetime.datetime(2023, 1, 12, tzinfo=datetime.UTC))
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

        post_mock = respx_mock.post(
            f"{MAILJET_API_URL}REST/contactslist/{NEW_ORIENTEURS_LISTID}/managemanycontacts"
        ).mock(return_value=httpx.Response(201, json={"Count": 1, "Data": [{"JobID": 123456789}], "Total": 1}))
        respx_mock.get(
            f"{MAILJET_API_URL}REST/contactslist/{NEW_ORIENTEURS_LISTID}/managemanycontacts/123456789"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "Count": 1,
                    "Data": [
                        {
                            "ContactsLists": [{"ListID": NEW_ORIENTEURS_LISTID, "Action": "addnoforce"}],
                            "Count": 1,
                            "Error": "",
                            "ErrorFile": "",
                            "JobStart": "2023-05-02T11:11:11",
                            "JobEnd": "2023-05-02T11:11:56",
                            "Status": "Completed",
                        }
                    ],
                    "Total": 1,
                },
            ),
        )
        call_command("new_users_to_mailjet", wet_run=True)
        [postcall] = post_mock.calls
        assert json.loads(postcall.request.content) == {
            "Action": "addnoforce",
            "Contacts": [
                {"Email": "billy.boo@mailinator.com", "Name": "Billy BOO"},
                {"Email": "sonny.sunder@mailinator.com", "Name": "Sonny SUNDER"},
                {"Email": "timmy.timber@mailinator.com", "Name": "Timmy TIMBER"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 3"),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: POST https://api.mailjet.com/v3/REST/contactslist/{NEW_ORIENTEURS_LISTID}/managemanycontacts "HTTP/1.1 201 Created"',  # noqa: E501
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: GET https://api.mailjet.com/v3/REST/contactslist/{NEW_ORIENTEURS_LISTID}/managemanycontacts/123456789 "HTTP/1.1 200 OK"',  # noqa: E501
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_ORIENTEURS_LISTID} in 45 seconds.",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                "Management command itou.users.management.commands.new_users_to_mailjet succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_batch(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

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
        post_mock = respx_mock.post(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts").mock(
            side_effect=[
                httpx.Response(201, json={"Count": 1, "Data": [{"JobID": 1}], "Total": 1}),
                httpx.Response(201, json={"Count": 1, "Data": [{"JobID": 2}], "Total": 1}),
            ]
        )
        respx_mock.get(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "Count": 1,
                    "Data": [
                        {
                            "ContactsLists": [{"ListID": NEW_SIAE_LISTID, "Action": "addnoforce"}],
                            "Count": 1,
                            "Error": "",
                            "ErrorFile": "",
                            "JobStart": "2023-05-02T11:11:11",
                            "JobEnd": "2023-05-02T11:12:00",
                            "Status": "Completed",
                        }
                    ],
                    "Total": 1,
                },
            ),
        )
        respx_mock.get(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/2").mock(
            return_value=httpx.Response(
                200,
                json={
                    "Count": 1,
                    "Data": [
                        {
                            "ContactsLists": [{"ListID": NEW_SIAE_LISTID, "Action": "addnoforce"}],
                            "Count": 1,
                            "Error": "",
                            "ErrorFile": "",
                            "JobStart": "2023-05-02T11:23:00",
                            "JobEnd": "2023-05-02T11:24:00",
                            "Status": "Completed",
                        }
                    ],
                    "Total": 1,
                },
            ),
        )
        with mock.patch("itou.users.management.commands.new_users_to_mailjet.Command.BATCH_SIZE", 1):
            call_command("new_users_to_mailjet", wet_run=True)
        [postcall1, postcall2] = post_mock.calls

        assert json.loads(postcall1.request.content) == {
            "Action": "addnoforce",
            "Contacts": [
                {"Email": "annie.amma@mailinator.com", "Name": "Annie AMMA"},
            ],
        }
        assert json.loads(postcall2.request.content) == {
            "Action": "addnoforce",
            "Contacts": [
                {"Email": "bob.bailey@mailinator.com", "Name": "Bob BAILEY"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 2"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: POST https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts "HTTP/1.1 201 Created"',  # noqa: E501
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: GET https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/1 "HTTP/1.1 200 OK"',  # noqa: E501
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_SIAE_LISTID} in 49 seconds.",
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: POST https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts "HTTP/1.1 201 Created"',  # noqa: E501
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: GET https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/2 "HTTP/1.1 200 OK"',  # noqa: E501
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_SIAE_LISTID} in 60 seconds.",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                "Management command itou.users.management.commands.new_users_to_mailjet succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_errors(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

        annie = EmployerFactory(
            first_name="Annie",
            last_name="Amma",
            email="annie.amma@mailinator.com",
        )
        CompanyMembershipFactory(user=annie, company__kind=CompanyKind.EI)
        post_mock = respx_mock.post(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts").mock(
            return_value=httpx.Response(201, json={"Count": 1, "Data": [{"JobID": 1}], "Total": 1}),
        )
        respx_mock.get(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "Count": 1,
                    "Data": [
                        {
                            "ContactsLists": [{"ListID": NEW_SIAE_LISTID, "Action": "addnoforce"}],
                            "Count": 1,
                            "Error": "The blips failed to blap.",
                            "ErrorFile": "https://mailjet.com/my-errors.html",
                            "JobStart": "2023-05-02T11:11:11",
                            "JobEnd": "2023-05-02T11:12:00",
                            "Status": "Error",
                        }
                    ],
                    "Total": 1,
                },
            ),
        )
        call_command("new_users_to_mailjet", wet_run=True)
        [postcall] = post_mock.calls

        assert json.loads(postcall.request.content) == {
            "Action": "addnoforce",
            "Contacts": [
                {"Email": "annie.amma@mailinator.com", "Name": "Annie AMMA"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 1"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: POST https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts "HTTP/1.1 201 Created"',  # noqa: E501
            ),
            (
                "httpx",
                logging.INFO,
                f'HTTP Request: GET https://api.mailjet.com/v3/REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts/1 "HTTP/1.1 200 OK"',  # noqa: E501
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.ERROR,
                f"MailJet errors for list ID {NEW_SIAE_LISTID}: The blips failed to blap.",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.ERROR,
                f"MailJet errors file for list ID {NEW_SIAE_LISTID}: https://mailjet.com/my-errors.html",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_SIAE_LISTID} in 49 seconds.",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                "Management command itou.users.management.commands.new_users_to_mailjet succeeded in 0.00 seconds",
            ),
        ]

    @freeze_time("2026-05-02")
    def test_wet_run_limits_history_to_a_year(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

        # Past users are ignored.
        CompanyMembershipFactory(
            user__date_joined=datetime.datetime(2025, 5, 1, tzinfo=datetime.UTC),
            company__kind=CompanyKind.EI,
        )
        post_mock = respx_mock.post(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts")
        call_command("new_users_to_mailjet", wet_run=True)
        assert post_mock.called is False
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                "Management command itou.users.management.commands.new_users_to_mailjet succeeded in 0.00 seconds",
            ),
        ]


@freeze_time("2023-05-01")
def test_update_job_seeker_coords(settings, capsys, respx_mock):
    js1 = JobSeekerWithAddressFactory(coords="POINT (2.387311 48.917735)", geocoding_score=0.65)  # score too low
    js2 = JobSeekerWithAddressFactory(coords=None, geocoding_score=0.9)  # no coords
    js3 = JobSeekerWithAddressFactory(coords="POINT (5.43567 12.123876)", geocoding_score=0.76)  # score too low
    JobSeekerWithAddressFactory(with_address_in_qpv=True)

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

    call_command("update_job_seeker_coords", wet_run=True)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == [
        "> about to geolocate count=3 objects without geolocation or with a low " "score.",
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
def test_pe_certify_users(settings, respx_mock, capsys, snapshot):
    user = JobSeekerFactory(
        pk=424242,
        first_name="Yoder",
        last_name="Olson",
        birthdate=datetime.date(1994, 2, 22),
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
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout == snapshot()

    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 9, 13, 0, 0, tzinfo=datetime.UTC
    )
    assert user.jobseeker_profile.pe_obfuscated_nir is None

    # reset the jobseeker profile
    user.jobseeker_profile.pe_last_certification_attempt_at = None
    user.jobseeker_profile.save(update_fields=["pe_last_certification_attempt_at"])

    # user found immediately
    respx_mock.post("https://pe.fake/rechercheindividucertifie/v1/rechercheIndividuCertifie").respond(
        200, json=API_RECHERCHE_RESULT_KNOWN
    )
    call_command("pe_certify_users", wet_run=True)
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == snapshot()

    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 9, 13, 0, 0, tzinfo=datetime.UTC
    )
    assert user.jobseeker_profile.pe_obfuscated_nir == "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"


@freeze_time("2022-09-13")
def test_pe_certify_users_with_swap(settings, respx_mock, capsys, snapshot):
    user = JobSeekerFactory(
        pk=424243,
        first_name="Balthazar",
        last_name="Durand",
        birthdate=datetime.date(1987, 6, 21),
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
    stdout, stderr = capsys.readouterr()
    assert stderr == ""
    assert stdout.splitlines() == snapshot()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 9, 13, 0, 0, tzinfo=datetime.UTC
    )
    assert user.jobseeker_profile.pe_obfuscated_nir == "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ"

    user.refresh_from_db()
    assert user.first_name == "Durand"
    assert user.last_name == "Balthazar"


def test_pe_certify_users_retry(capsys, snapshot):
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
    stdout, stderr = capsys.readouterr()

    def recherche_call(user, swap):
        return mock.call(
            user.first_name if not swap else user.last_name,
            user.last_name if not swap else user.first_name,
            user.birthdate,
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


class TestCommandNotifyAndDeleteInactiveJobSeekers:
    @freeze_time("2024-01-01")
    def test_notify(self, mailoutbox, snapshot):
        LONG_TIME_AGO = timezone.now() - datetime.timedelta(days=500)
        OUTSIDE_GRACE_PERIOD = timezone.now() - datetime.timedelta(days=31)
        INSIDE_GRACE_PERIOD = timezone.now() - datetime.timedelta(days=3)

        # Users that should have their upcoming_deletion_notified_at cleaned up
        notified_job_seeker_reconnected_since = JobSeekerFactory(
            date_joined=LONG_TIME_AGO,
            upcoming_deletion_notified_at=OUTSIDE_GRACE_PERIOD,
            last_login=timezone.now(),
        )
        notified_job_seeker_with_new_job_application = JobApplicationFactory(
            job_seeker__date_joined=LONG_TIME_AGO,
            job_seeker__upcoming_deletion_notified_at=timezone.now() - datetime.timedelta(days=31),
        ).job_seeker
        notified_job_seeker_with_new_diagnosis = EligibilityDiagnosisFactory(
            job_seeker__date_joined=LONG_TIME_AGO,
            job_seeker__upcoming_deletion_notified_at=timezone.now() - datetime.timedelta(days=31),
        ).job_seeker
        notified_job_seeker_with_new_geiq_diagnosis = GEIQEligibilityDiagnosisFactory(
            with_prescriber=True,
            job_seeker__date_joined=LONG_TIME_AGO,
            job_seeker__upcoming_deletion_notified_at=timezone.now() - datetime.timedelta(days=31),
        ).job_seeker

        # Users that should be notified
        inactive_old_job_seeker = JobSeekerFactory(
            first_name="Jen",
            last_name="Manvai",
            date_joined=LONG_TIME_AGO,
        )

        # Users that should be ignored
        inactive_recent_job_seeker = JobSeekerFactory(date_joined=timezone.now())
        active_old_job_seeker = JobSeekerFactory(date_joined=LONG_TIME_AGO, last_login=timezone.now())
        inactive_old_job_seeker_with_approval = ApprovalFactory(
            user__date_joined=LONG_TIME_AGO,
            created_at=LONG_TIME_AGO,
        ).user
        inactive_old_job_seeker_with_new_job_application = JobApplicationFactory(
            job_seeker__date_joined=LONG_TIME_AGO,
        ).job_seeker
        inactive_old_job_seeker_with_old_accepted_job_application = JobApplicationFactory(
            job_seeker__date_joined=LONG_TIME_AGO,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            created_at=LONG_TIME_AGO,
        ).job_seeker
        inactive_old_job_seeker_with_new_diagnosis = EligibilityDiagnosisFactory(
            job_seeker__date_joined=LONG_TIME_AGO,
        ).job_seeker
        inactive_old_job_seeker_with_new_geiq_diagnosis = GEIQEligibilityDiagnosisFactory(
            with_prescriber=True,
            job_seeker__date_joined=LONG_TIME_AGO,
        ).job_seeker
        notified_job_seeker_without_recent_activity_but_inside_grace_period = JobSeekerFactory(
            first_name="Jen",
            last_name="Suiplula",
            date_joined=LONG_TIME_AGO,
            upcoming_deletion_notified_at=INSIDE_GRACE_PERIOD,
        )

        # Users that should be deleted
        notified_job_seeker_without_recent_activity = JobSeekerFactory(
            first_name="Jen",
            last_name="Suiplula",
            date_joined=LONG_TIME_AGO,
            upcoming_deletion_notified_at=OUTSIDE_GRACE_PERIOD,
        )

        # Launch in dry run
        call_command("notify_and_delete_inactive_job_seekers", wet_run=False)
        # No jobseeker deleted
        assert set(User.objects.filter(kind=UserKind.JOB_SEEKER)) == {
            active_old_job_seeker,
            inactive_old_job_seeker,
            inactive_old_job_seeker_with_approval,
            inactive_old_job_seeker_with_new_diagnosis,
            inactive_old_job_seeker_with_new_geiq_diagnosis,
            inactive_old_job_seeker_with_new_job_application,
            inactive_old_job_seeker_with_old_accepted_job_application,
            inactive_recent_job_seeker,
            notified_job_seeker_reconnected_since,
            notified_job_seeker_with_new_diagnosis,
            notified_job_seeker_with_new_geiq_diagnosis,
            notified_job_seeker_with_new_job_application,
            notified_job_seeker_without_recent_activity,
            notified_job_seeker_without_recent_activity_but_inside_grace_period,
        }
        # No upcoming_deletion_notified_at updated
        assert set(User.objects.filter(upcoming_deletion_notified_at__isnull=False)) == {
            notified_job_seeker_reconnected_since,
            notified_job_seeker_with_new_diagnosis,
            notified_job_seeker_with_new_geiq_diagnosis,
            notified_job_seeker_with_new_job_application,
            notified_job_seeker_without_recent_activity,
            notified_job_seeker_without_recent_activity_but_inside_grace_period,
        }
        # No mail sent
        assert len(mailoutbox) == 0

        # Now in wet run
        call_command("notify_and_delete_inactive_job_seekers", wet_run=True)
        # notified_job_seeker_without_recent_activity has been removed
        assert set(User.objects.filter(kind=UserKind.JOB_SEEKER)) == {
            active_old_job_seeker,
            inactive_old_job_seeker,
            inactive_old_job_seeker_with_approval,
            inactive_old_job_seeker_with_new_diagnosis,
            inactive_old_job_seeker_with_new_geiq_diagnosis,
            inactive_old_job_seeker_with_new_job_application,
            inactive_old_job_seeker_with_old_accepted_job_application,
            inactive_recent_job_seeker,
            notified_job_seeker_reconnected_since,
            notified_job_seeker_with_new_diagnosis,
            notified_job_seeker_with_new_geiq_diagnosis,
            notified_job_seeker_with_new_job_application,
            notified_job_seeker_without_recent_activity_but_inside_grace_period,
        }
        # newly inactive user has been notified & notified users with recent activities have been reset
        assert set(User.objects.filter(upcoming_deletion_notified_at__isnull=False)) == {
            inactive_old_job_seeker,
            notified_job_seeker_without_recent_activity_but_inside_grace_period,
        }
        # 2 mails were sent: one for the notification and one for the deletion
        assert len(mailoutbox) == 2
        upcoming_deletion_email = mailoutbox[0]
        assert upcoming_deletion_email.subject == "Information avant suppression de votre compte candidat"
        assert upcoming_deletion_email.body == snapshot(name="upcoming deletion email body")

        deletion_email = mailoutbox[1]
        assert deletion_email.subject == "Suppression de votre compte candidat"
        assert deletion_email.body == snapshot(name="deletion email body")
