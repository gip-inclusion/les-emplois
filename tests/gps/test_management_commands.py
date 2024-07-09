import datetime
from io import StringIO

from django.conf import settings
from django.core import management
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from itou.companies.enums import CompanyKind
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.enums import JobApplicationState
from tests.companies.factories import CompanyWith4MembershipsFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.gps.factories import FollowUpGroupFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.users.factories import EmployerFactory, ItouStaffFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.test import TestCase


# To be able to use assertCountEqual
@override_settings(GPS_GROUPS_CREATED_BY_EMAIL="rocking@developer.com")
class GpsManagementCommandTest(TestCase):
    def setUp(self):
        ItouStaffFactory(email="rocking@developer.com")

    def call_command(self, management_command_name=None, *args, **kwargs):
        """Redirect standard outputs from management command to StringIO objects for testing purposes."""

        out = StringIO()
        err = StringIO()

        assert management_command_name, "Management command name must be provided"

        management.call_command(
            management_command_name,
            *args,
            stdout=out,
            stderr=err,
            **kwargs,
        )

        return out.getvalue(), err.getvalue()

    def test_group_creation(self):
        should_be_created_groups_counter = 0
        should_be_created_memberships = 0
        # A group should be created for every beneficiary with a least one job application not new.
        job_application = JobApplicationFactory(
            state=JobApplicationState.NEW,
        )
        JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=job_application.job_seeker,
            eligibility_diagnosis=job_application.eligibility_diagnosis,
        )
        should_be_created_groups_counter += 1
        should_be_created_memberships += 1  # processing job_application sender
        should_be_created_memberships += 1  # eligibility diagnosis (new job_app sender)
        assert job_application.job_seeker.eligibility_diagnoses.count() == 1

        self.call_command("init_follow_up_groups", wet_run=True)

        assert FollowUpGroup.objects.count() == should_be_created_groups_counter
        assert FollowUpGroupMembership.objects.count() == should_be_created_memberships

        company = CompanyWith4MembershipsFactory()

        job_application_with_approval = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationState.PROCESSING,
            to_company=company,
            eligibility_diagnosis__author=company.members.first(),
            approval__eligibility_diagnosis__to_company=company,
        )
        # Needed to create the transition log entries
        user_who_accepted = job_application_with_approval.to_company.members.last()
        job_application_with_approval.accept(user=user_who_accepted)
        should_be_created_groups_counter += 1
        should_be_created_memberships += 3  # employer who accepted, employer who made the diagnosis and prescriber

        # No job application linked. A group should not be created.
        JobSeekerFactory()

        # Only one new job application. A group should not be created.
        JobApplicationFactory(state=JobApplicationState.NEW)

        # Empty group!
        # One processing job application sent by a job seeker.
        # A group should not be created.
        JobApplicationSentByJobSeekerFactory(state=JobApplicationState.PROCESSING, eligibility_diagnosis=None)

        self.call_command("init_follow_up_groups", wet_run=True)

        # We should have created one follow-up group per job_application
        assert FollowUpGroup.objects.count() == should_be_created_groups_counter

        # We should have crated 4 memberships, one for the first job_application sender
        # 3 for the second job_application: one for the sender, the other for the user
        # who accepted the job_application and the third for the author of the diagnosis
        # assert FollowUpGroupMembership.objects.count() == 4
        assert FollowUpGroupMembership.objects.count() == should_be_created_memberships

        self.assertCountEqual(
            job_application_with_approval.job_seeker.follow_up_group.members.all(),
            [
                job_application_with_approval.sender,
                job_application_with_approval.eligibility_diagnosis.author,
                user_who_accepted,
            ],
        )

        ## Jop Application with GEIQ approval
        job_application_geiq_diagnosis = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.PROCESSING,
            with_geiq_eligibility_diagnosis_from_prescriber=True,
            to_company=company,
            geiq_eligibility_diagnosis__author=company.members.first(),
        )
        should_be_created_groups_counter += 1

        self.call_command("init_follow_up_groups", wet_run=True)

        # One more
        assert FollowUpGroup.objects.count() == should_be_created_groups_counter

        self.assertCountEqual(
            job_application_geiq_diagnosis.job_seeker.follow_up_group.members.all(),
            [
                job_application_geiq_diagnosis.sender,
                job_application_geiq_diagnosis.geiq_eligibility_diagnosis.author,
            ],
        )

        ## Job application sent by job seeker.
        prescriber = PrescriberFactory()
        job_application_sent_by_job_seeker = JobApplicationSentByJobSeekerFactory(
            job_seeker__first_name="Dave",
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis__author=prescriber,
        )
        should_be_created_groups_counter += 1
        self.call_command("init_follow_up_groups", wet_run=True)
        assert FollowUpGroup.objects.count() == should_be_created_groups_counter
        beneficiary = job_application_sent_by_job_seeker.job_seeker
        group = FollowUpGroup.objects.get(beneficiary=beneficiary)
        assert not group.memberships.filter(member=beneficiary).exists()

    def test_job_application_accepted(self):
        JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.PROCESSING,
        )

        job_application_accepted = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.PROCESSING,
        )
        user = job_application_accepted.to_company.members.first()
        job_application_accepted.accept(user=user)

        assert FollowUpGroup.objects.count() == 0
        assert FollowUpGroupMembership.objects.count() == 0

        self.call_command("init_follow_up_groups", wet_run=True)

        # We should have created one follow-up group per job_application
        assert FollowUpGroup.objects.count() == 2

        # We should have crated 3 memberships, one for the first job_application sender
        # and 2 for the second job_application: one for the sender and the other for the user
        # who accepted the job_application
        assert FollowUpGroupMembership.objects.count() == 3

        self.assertCountEqual(
            job_application_accepted.job_seeker.follow_up_group.members.all(), [user, job_application_accepted.sender]
        )

    def test_job_application_sender_job_seeker(self):
        JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.NEW, to_company__kind=CompanyKind.GEIQ, eligibility_diagnosis=None
        )

        assert FollowUpGroup.objects.count() == 0
        assert FollowUpGroupMembership.objects.count() == 0

        self.call_command("init_follow_up_groups", wet_run=True)

        # We should not create anything
        assert FollowUpGroup.objects.count() == 0
        assert FollowUpGroupMembership.objects.count() == 0

    def test_job_application_sender_prescriber(self):
        # First job_application with a new prescriber and beneficiary
        first_job_application = JobApplicationFactory(
            state=JobApplicationState.NEW,
            to_company__kind=CompanyKind.GEIQ,
            eligibility_diagnosis=None,
        )

        # Second job application with the same sender as the first one
        second_job_application = JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.GEIQ,
            eligibility_diagnosis=None,
            sender=first_job_application.sender,
        )

        # We create another random JobApplication
        JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.GEIQ,
            eligibility_diagnosis=None,
        )

        # We create a FollowUpGroup for the first_job_applicaton with 4 members, one of the members being
        # the firt_job_application sender
        first_beneficiary_group = FollowUpGroupFactory(
            beneficiary=first_job_application.job_seeker,
            memberships=4,
            memberships__member=first_job_application.sender,
        )

        assert FollowUpGroup.objects.count() == 1

        self.assertCountEqual(
            FollowUpGroup.objects.filter(beneficiary=first_job_application.job_seeker)
            .filter(members=first_job_application.sender)
            .all(),
            [first_beneficiary_group],
        )

        assert FollowUpGroupMembership.objects.count() == 4

        self.call_command("init_follow_up_groups", wet_run=True)

        # As we are already part of the first_beneficiary group, having a job application for it
        # should not create a new membership, but a membership for the second_job_application should
        # be created
        assert FollowUpGroupMembership.objects.count() == 6
        memberships = FollowUpGroupMembership.objects.filter(member=first_job_application.sender).all()

        assert len(memberships) == 2

        all_groups = FollowUpGroup.objects.all()
        first_sender_groups = FollowUpGroup.objects.filter(members=first_job_application.sender).all()

        # Groups should not contain any job_seeker
        assert all([not member.is_job_seeker for group in all_groups for member in group.members.all()])

        # The already created group in fixtures should still be part of the groups after the command call
        assert first_beneficiary_group in all_groups

        # 2 new groups should have be created
        assert len(all_groups) == 3

        new_groups = [group for group in all_groups if group.id != first_beneficiary_group.id]

        # One group should have the seconde_job_application job_seeker as beneficiary
        [new_first_group] = [group for group in new_groups if group.beneficiary == second_job_application.job_seeker]

        # The other one should have totally new beneficiary and members
        [_] = [
            group
            for group in new_groups
            if group.beneficiary != first_job_application.job_seeker
            and first_job_application.sender not in group.members.all()
        ]

        # By default all the new memberships are active
        assert all([membership.is_active for group in new_groups for membership in group.memberships.all()])

        # By default all the added members are ot referent
        assert all([not membership.is_referent for group in new_groups for membership in group.memberships.all()])

        # The members of the new group for the first application should only be composed of
        # the first_job_application sender
        self.assertCountEqual(new_first_group.members.all(), [first_job_application.sender])

        # Calling the command twice should be ok
        self.call_command("init_follow_up_groups", wet_run=True)

        self.assertCountEqual(
            FollowUpGroupMembership.objects.filter(member=first_job_application.sender).all(), memberships
        )

        assert FollowUpGroupMembership.objects.count() == 6
        self.assertCountEqual(
            FollowUpGroup.objects.filter(members=first_job_application.sender).all(), first_sender_groups
        )

    def test_group_create_at_update(self):
        job_seeker = JobSeekerFactory()
        prescriber = PrescriberFactory()
        employer = EmployerFactory()
        with freeze_time("2022-06-01 00:00:01"):
            # A sent job application in NEW status (ignored)
            new_job_app = JobApplicationFactory(
                job_seeker=job_seeker, sender=prescriber, state=JobApplicationState.NEW, eligibility_diagnosis=None
            )
        with freeze_time("2022-06-01 00:00:02"):
            # >>> Prescriber membership & group creation date
            prescriber_membership_date = timezone.now()
            # A first iae diag from the prescriber (this is the date of the prescriber membership)
            IAEEligibilityDiagnosisFactory(job_seeker=job_seeker, from_prescriber=True, author=prescriber)
        with freeze_time("2022-06-01 00:00:03"):
            # Another iae diag from the prescriber
            IAEEligibilityDiagnosisFactory(job_seeker=job_seeker, from_prescriber=True, author=prescriber)
        with freeze_time("2022-06-01 00:00:04"):
            # A geiq diag stil from the prescriber
            GEIQEligibilityDiagnosisFactory(job_seeker=job_seeker, from_prescriber=True, author=prescriber)
        with freeze_time("2022-06-01 00:00:05"):
            # Another sent job application
            accepted_job_app = JobApplicationFactory(
                job_seeker=job_seeker, sender=prescriber, state=JobApplicationState.NEW
            )
        with freeze_time("2022-06-01 00:00:06"):
            # the employer process the last job app
            accepted_job_app.process(user=employer)
        with freeze_time("2022-06-01 00:00:07"):
            # >>> Employer membership creation date
            employer_membership_date = timezone.now()
            # the employer accepts the last job app
            accepted_job_app.accept(user=employer)
        with freeze_time("2022-06-01 00:00:08"):
            # Another iae diag from the employer
            IAEEligibilityDiagnosisFactory(job_seeker=job_seeker, from_employer=True, author=employer)

        # reset first job app that was rendered obsolete (this instance is still new)
        new_job_app.save()

        # initialise the groups
        init_created_at = datetime.datetime.combine(
            settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(10, 0, 0), tzinfo=datetime.UTC
        )
        with freeze_time(init_created_at):
            self.call_command("init_follow_up_groups", wet_run=True)

        assert list(
            FollowUpGroup.objects.values_list("beneficiary_id", "created_at", "created_in_bulk", "updated_at")
        ) == [
            (job_seeker.pk, init_created_at, True, init_created_at),
        ]
        assert list(
            FollowUpGroupMembership.objects.order_by("member_id").values_list(
                "member_id", "created_at", "created_in_bulk", "updated_at"
            )
        ) == [
            (prescriber.pk, init_created_at, True, init_created_at),
            (employer.pk, init_created_at, True, init_created_at),
        ]

        # Update created_at
        with freeze_time(timezone.now()):
            update_script_launched_at = timezone.now()
            self.call_command("update_follow_up_groups_member_created_at", wet_run=True)
        assert list(
            FollowUpGroup.objects.values_list("beneficiary_id", "created_at", "created_in_bulk", "updated_at")
        ) == [
            (job_seeker.pk, prescriber_membership_date, True, update_script_launched_at),
        ]
        assert list(
            FollowUpGroupMembership.objects.order_by("member_id").values_list(
                "member_id", "created_at", "created_in_bulk", "updated_at"
            )
        ) == [
            (prescriber.pk, prescriber_membership_date, True, update_script_launched_at),
            (employer.pk, employer_membership_date, True, update_script_launched_at),
        ]
