import pytest
from django.core.management import call_command

from tests.users.factories import JobSeekerFactory


@pytest.mark.parametrize(
    "birth_name,last_name,expected_last_name",
    (
        ("", "", ""),  # empty names, no change
        ("", "Smith", "Smith"),  # no birth name, no change
        ("Smith", "", "Smith"),  # missing last name, update
        ("Smith", "SMITH", "Smith"),  # "same" name, overwrite with birth name
        ("ßmith", "Ssmith", "ßmith"),  # "same" name, overwrite with birth name
        ("Smith", "Doe", "Doe"),  # different name, no change
    ),
)
def test_check_last_name(birth_name, last_name, expected_last_name):
    user = JobSeekerFactory(last_name=last_name, jobseeker_profile__birth_name=birth_name)

    call_command("check_last_name", fix=True, wet_run=True)

    user.refresh_from_db()
    assert user.last_name == expected_last_name
