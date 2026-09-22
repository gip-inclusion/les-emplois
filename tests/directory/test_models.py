from itou.directory.models import ContactMessage, DirectoryProfile
from tests.users.factories import ProfessionalFactory


def test_directory_profile_is_opted_in_by_default():
    profile = DirectoryProfile.objects.create(user=ProfessionalFactory())

    assert profile.is_opted_out is False


def test_contact_message_does_not_store_body():
    field_names = {field.name for field in ContactMessage._meta.get_fields()}

    assert "body" not in field_names
    assert {"sender", "recipient_id", "subject", "custom_subject", "created_at"} <= field_names
