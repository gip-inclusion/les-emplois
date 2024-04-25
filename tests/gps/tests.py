from itou.users.models import User
from tests.gps.factories import FollowUpGroupFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory


def test_user_autocomplete():

    member = PrescriberFactory(first_name="gps member first_name")
    beneficiary = JobSeekerFactory(first_name="gps beneficiary first_name")
    another_beneficiary = JobSeekerFactory(first_name="gps another beneficiary first_name")

    FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=member)
    FollowUpGroupFactory(beneficiary=another_beneficiary, memberships=2)

    assert User.objects.autocomplete("gps").count() == 3
    assert User.objects.autocomplete("gps member").count() == 1

    # We should not get ourself nor the other user because we are a member of his group
    users = User.objects.autocomplete("gps", current_user=member)
    assert users.count() == 1
    assert users[0].id == another_beneficiary.id
