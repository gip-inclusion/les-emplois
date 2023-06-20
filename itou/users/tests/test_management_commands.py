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

from itou.approvals.factories import ApprovalFactory
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from itou.job_applications.models import JobApplication
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.factories import (
    PrescriberFactory,
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberPoleEmploiFactory,
)
from itou.siaes.enums import SIAE_WITH_CONVENTION_KINDS, SiaeKind
from itou.siaes.factories import SiaeMembershipFactory
from itou.users.factories import JobSeekerFactory, JobSeekerWithAddressFactory, SiaeStaffFactory
from itou.users.management.commands.new_users_to_mailjet import (
    MAILJET_API_URL,
    NEW_ORIENTEURS_LISTID,
    NEW_PE_LISTID,
    NEW_PRESCRIBERS_LISTID,
    NEW_SIAE_LISTID,
)
from itou.users.models import User
from itou.utils.mocks.pole_emploi import API_RECHERCHE_ERROR, API_RECHERCHE_RESULT_KNOWN
from itou.utils.test import TestCase


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
            "job_seeker__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1`.
        job_app1 = JobApplicationFactory(with_approval=True, job_seeker__nir="", **kwargs)
        user1 = job_app1.job_seeker

        assert user1.nir == ""
        assert 1 == user1.approvals.count()
        assert 1 == user1.job_applications.count()
        assert 1 == user1.eligibility_diagnoses.count()

        # Create `user2`.
        job_app2 = JobApplicationFactory(job_seeker__nir="", **kwargs)
        user2 = job_app2.job_seeker

        assert user2.nir == ""
        assert 0 == user2.approvals.count()
        assert 1 == user2.job_applications.count()
        assert 1 == user2.eligibility_diagnoses.count()

        # Create `user3`.
        job_app3 = JobApplicationFactory(**kwargs)
        user3 = job_app3.job_seeker
        expected_nir = user3.nir

        assert user3.nir
        assert 0 == user3.approvals.count()
        assert 1 == user3.job_applications.count()
        assert 1 == user3.eligibility_diagnoses.count()

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_xlsx=True, wet_run=True)

        # If only one NIR exists for all the duplicates, it should
        # be reassigned to the target account.
        user1.refresh_from_db()
        assert user1.nir == expected_nir

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
            "job_seeker__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1` through a job application sent by him.
        job_app1 = JobApplicationSentByJobSeekerFactory(job_seeker__nir="", **kwargs)
        user1 = job_app1.job_seeker

        assert 1 == user1.job_applications.count()
        assert job_app1.sender == user1

        # Create `user2` through a job application sent by him.
        job_app2 = JobApplicationSentByJobSeekerFactory(job_seeker__nir="", **kwargs)
        user2 = job_app2.job_seeker

        assert 1 == user2.job_applications.count()
        assert job_app2.sender == user2

        # Create `user3` through a job application sent by a prescriber.
        job_app3 = JobApplicationFactory(job_seeker__nir="", **kwargs)
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
        admin_group = Group.objects.all()[0]
        assert admin_group.name == "itou-admin"
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
            "change_laborinspectorinvitation",
            "delete_laborinspectorinvitation",
            "view_laborinspectorinvitation",
            "change_prescriberwithorginvitation",
            "delete_prescriberwithorginvitation",
            "view_prescriberwithorginvitation",
            "change_siaestaffinvitation",
            "delete_siaestaffinvitation",
            "view_siaestaffinvitation",
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
            "view_evaluatedadministrativecriteria",
            "view_evaluatedjobapplication",
            "view_evaluatedsiae",
            "view_evaluationcampaign",
            "view_sanctions",
            "add_siae",
            "change_siae",
            "view_siae",
            "change_siaeconvention",
            "view_siaeconvention",
            "view_siaefinancialannex",
            "add_siaejobdescription",
            "change_siaejobdescription",
            "delete_siaejobdescription",
            "view_siaejobdescription",
            "add_siaemembership",
            "change_siaemembership",
            "delete_siaemembership",
            "view_siaemembership",
            "change_jobseekerprofile",
            "view_jobseekerprofile",
            "add_user",
            "change_user",
            "view_user",
        ]
        support_group = Group.objects.all()[1]
        assert support_group.name == "itou-support-externe"
        assert [perm.codename for perm in support_group.permissions.all()] == [
            "view_emailaddress",
            "view_approval",
            "view_poleemploiapproval",
            "view_prolongation",
            "view_suspension",
            "view_commune",
            "view_country",
            "view_department",
            "view_city",
            "view_administrativecriteria",
            "view_eligibilitydiagnosis",
            "view_selectedadministrativecriteria",
            "view_employeerecord",
            "view_institution",
            "view_institutionmembership",
            "view_laborinspectorinvitation",
            "view_prescriberwithorginvitation",
            "view_siaestaffinvitation",
            "view_jobapplication",
            "view_jobapplicationtransitionlog",
            "view_appellation",
            "view_rome",
            "view_prescribermembership",
            "view_prescriberorganization",
            "view_siae",
            "view_siaeconvention",
            "view_siaefinancialannex",
            "view_siaejobdescription",
            "view_siaemembership",
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
        for kind in set(SiaeKind) - set(SIAE_WITH_CONVENTION_KINDS):
            SiaeMembershipFactory(user__with_verified_email=True, siae__kind=kind)
        # Missing verified email.
        SiaeMembershipFactory(siae__kind=SiaeKind.EI)
        not_primary = SiaeMembershipFactory(siae__kind=SiaeKind.EI).user
        EmailAddress.objects.create(user=not_primary, email=not_primary.email, primary=False, verified=True)
        # Past users are ignored.
        SiaeMembershipFactory(
            user__date_joined=datetime.datetime(2023, 1, 12, tzinfo=datetime.UTC),
            user__with_verified_email=True,
            siae__kind=SiaeKind.EI,
        )
        # Inactive memberships are ignored.
        SiaeMembershipFactory(user__with_verified_email=True, siae__kind=SiaeKind.EI, is_active=False)
        # Inactive users are ignored.
        SiaeMembershipFactory(user__with_verified_email=True, user__is_active=False, siae__kind=SiaeKind.EI)
        # New email not verified is ignored.
        changed_email = SiaeMembershipFactory(user__with_verified_email=True, siae__kind=SiaeKind.EI).user
        changed_email.email = "changed@mailinator.com"
        changed_email.save(update_fields=["email"])

        annie = SiaeStaffFactory(
            first_name="Annie",
            last_name="Amma",
            email="annie.amma@mailinator.com",
            with_verified_email=True,
        )
        bob = SiaeStaffFactory(
            first_name="Bob",
            last_name="Bailey",
            email="bob.bailey@mailinator.com",
            with_verified_email=True,
        )
        cindy = SiaeStaffFactory(
            first_name="Cindy",
            last_name="Cinnamon",
            email="cindy.cinnamon@mailinator.com",
            with_verified_email=True,
        )
        dave = SiaeStaffFactory(
            first_name="Dave",
            last_name="Doll",
            email="dave.doll@mailinator.com",
            with_verified_email=True,
        )
        eve = SiaeStaffFactory(
            first_name="Eve",
            last_name="Ebi",
            email="eve.ebi@mailinator.com",
            with_verified_email=True,
        )
        SiaeMembershipFactory(user=annie, siae__kind=SiaeKind.EI)
        SiaeMembershipFactory(user=bob, siae__kind=SiaeKind.AI)
        SiaeMembershipFactory(user=cindy, siae__kind=SiaeKind.ACI)
        SiaeMembershipFactory(user=dave, siae__kind=SiaeKind.ETTI)
        SiaeMembershipFactory(user=eve, siae__kind=SiaeKind.EITI)
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
                {"Email": "annie.amma@mailinator.com", "Name": "Annie Amma"},
                {"Email": "bob.bailey@mailinator.com", "Name": "Bob Bailey"},
                {"Email": "cindy.cinnamon@mailinator.com", "Name": "Cindy Cinnamon"},
                {"Email": "dave.doll@mailinator.com", "Name": "Dave Doll"},
                {"Email": "eve.ebi@mailinator.com", "Name": "Eve Ebi"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 5"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_SIAE_LISTID} in 5025 seconds.",
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
            with_verified_email=True,
        )
        PrescriberMembershipFactory(user=alice, organization=pe)
        justin = PrescriberFactory(
            first_name="Justin",
            last_name="Wood",
            email="justin.wood@mailinator.com",
            with_verified_email=True,
        )
        PrescriberMembershipFactory(user=justin, organization=other_org)

        for organization in [pe, other_org]:
            # Ignored, email is not the primary email.
            not_primary = PrescriberMembershipFactory(organization=organization).user
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
            # New email not verified is ignored.
            changed_email = PrescriberMembershipFactory(user__with_verified_email=True, organization=organization).user
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
            "Contacts": [{"Email": "alice.aamar@mailinator.com", "Name": "Alice Aamar"}],
        }
        [other_org_postcall] = other_org_post_mock.calls
        assert json.loads(other_org_postcall.request.content) == {
            "Action": "addnoforce",
            "Contacts": [
                {"Email": "alice.aamar@mailinator.com", "Name": "Alice Aamar"},
                {"Email": "justin.wood@mailinator.com", "Name": "Justin Wood"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 1"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 2"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_PE_LISTID} in 45 seconds.",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_PRESCRIBERS_LISTID} in 45 seconds.",
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
            with_verified_email=True,
        )
        sonny = PrescriberFactory(
            first_name="Sonny",
            last_name="Sunder",
            email="sonny.sunder@mailinator.com",
            with_verified_email=True,
        )
        # Inactive memberships are considered orienteur.
        PrescriberMembershipFactory(user=sonny, is_active=False)
        # Members of unauthorized organizations are orienteurs.
        timmy = PrescriberFactory(
            first_name="Timmy",
            last_name="Timber",
            email="timmy.timber@mailinator.com",
            with_verified_email=True,
        )
        timmy = PrescriberMembershipFactory(user=timmy, organization__kind=PrescriberOrganizationKind.OTHER)
        # Past users are ignored.
        PrescriberFactory(with_verified_email=True, date_joined=datetime.datetime(2023, 1, 12, tzinfo=datetime.UTC))
        # Inactive users are ignored.
        PrescriberFactory(
            with_verified_email=True,
            is_active=False,
            date_joined=datetime.datetime(2023, 1, 12, tzinfo=datetime.UTC),
        )
        # Ignored, email is not the primary email.
        not_primary = PrescriberFactory()
        EmailAddress.objects.create(user=not_primary, email=not_primary.email, primary=False, verified=True)
        # New email not verified is ignored.
        changed_email = PrescriberFactory(with_verified_email=True)
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
                {"Email": "billy.boo@mailinator.com", "Name": "Billy Boo"},
                {"Email": "sonny.sunder@mailinator.com", "Name": "Sonny Sunder"},
                {"Email": "timmy.timber@mailinator.com", "Name": "Timmy Timber"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 3"),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_ORIENTEURS_LISTID} in 45 seconds.",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_batch(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

        annie = SiaeStaffFactory(
            first_name="Annie",
            last_name="Amma",
            email="annie.amma@mailinator.com",
            with_verified_email=True,
        )
        bob = SiaeStaffFactory(
            first_name="Bob",
            last_name="Bailey",
            email="bob.bailey@mailinator.com",
            with_verified_email=True,
        )
        SiaeMembershipFactory(user=annie, siae__kind=SiaeKind.EI)
        SiaeMembershipFactory(user=bob, siae__kind=SiaeKind.AI)
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
                {"Email": "annie.amma@mailinator.com", "Name": "Annie Amma"},
            ],
        }
        assert json.loads(postcall2.request.content) == {
            "Action": "addnoforce",
            "Contacts": [
                {"Email": "bob.bailey@mailinator.com", "Name": "Bob Bailey"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 2"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_SIAE_LISTID} in 49 seconds.",
            ),
            (
                "itou.users.management.commands.new_users_to_mailjet",
                logging.INFO,
                f"MailJet processed batch for list ID {NEW_SIAE_LISTID} in 60 seconds.",
            ),
        ]

    @freeze_time("2023-05-02")
    def test_wet_run_errors(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

        annie = SiaeStaffFactory(
            first_name="Annie",
            last_name="Amma",
            email="annie.amma@mailinator.com",
            with_verified_email=True,
        )
        SiaeMembershipFactory(user=annie, siae__kind=SiaeKind.EI)
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
                {"Email": "annie.amma@mailinator.com", "Name": "Annie Amma"},
            ],
        }
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 1"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
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
        ]

    @freeze_time("2026-05-02")
    def test_wet_run_limits_history_to_a_year(self, caplog, respx_mock, settings):
        settings.MAILJET_API_KEY = "MAILJET_KEY"
        settings.MAILJET_SECRET_KEY = "MAILJET_SECRET_KEY"

        # Past users are ignored.
        SiaeMembershipFactory(
            user__date_joined=datetime.datetime(2025, 5, 1, tzinfo=datetime.UTC),
            user__with_verified_email=True,
            siae__kind=SiaeKind.EI,
        )
        post_mock = respx_mock.post(f"{MAILJET_API_URL}REST/contactslist/{NEW_SIAE_LISTID}/managemanycontacts")
        call_command("new_users_to_mailjet", wet_run=True)
        assert post_mock.called is False
        assert caplog.record_tuples == [
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "SIAE users count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "PE prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Prescribers count: 0"),
            ("itou.users.management.commands.new_users_to_mailjet", logging.INFO, "Orienteurs count: 0"),
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
        nir="194022734304328",
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
        nir="187062112345678",
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
