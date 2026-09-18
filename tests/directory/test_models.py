from itou.directory.models import DirectoryProfile
from tests.users.factories import ProfessionalFactory


def test_directory_profile_is_opted_in_by_default():
    profile = DirectoryProfile.objects.create(user=ProfessionalFactory())

    assert profile.is_opted_out is False
