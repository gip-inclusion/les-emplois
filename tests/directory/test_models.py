from itou.directory.models import ContactMessage


def test_contact_message_does_not_store_body():
    field_names = {field.name for field in ContactMessage._meta.get_fields()}

    assert "body" not in field_names
    assert {"sender", "recipient_id", "subject", "custom_subject", "created_at"} <= field_names
