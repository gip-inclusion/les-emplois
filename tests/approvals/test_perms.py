from itou.approvals.perms import can_view_approval_details
from tests.approvals.factories import ApprovalFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory
from tests.utils.testing import get_request


def test_can_view_approval_details():
    approval = ApprovalFactory()

    for user in [
        approval.user,
        JobApplicationFactory(
            job_seeker=approval.user, sent_by_authorized_prescriber_organisation=True
        ).sender,  # linked authorized prescriber
        JobApplicationFactory(job_seeker=approval.user).to_company.members.first(),  # employer whom received a job app
        JobApplicationFactory(job_seeker=approval.user, sent_by_company=True).sender,  # employer who sent a job app
    ]:
        request = get_request(user)
        assert can_view_approval_details(request, approval) is True

    for bad_user in [
        JobSeekerFactory(),  # another job seeker
        PrescriberMembershipFactory(organization__authorized=True).user,  # a random authorized prescriber
        JobApplicationFactory(job_seeker=approval.user).sender,  # a non authorized prescriber linked to the job seeker
        EmployerFactory(with_company=True),
    ]:
        request = get_request(bad_user)
        assert can_view_approval_details(request, approval) is False
