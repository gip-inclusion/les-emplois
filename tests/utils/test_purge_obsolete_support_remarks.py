import uuid

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

from itou.utils.models import PkSupportRemark, UUIDSupportRemark
from tests.job_applications.factories import JobApplicationFactory


@pytest.mark.parametrize("wet_run", [True, False])
def test_purge_orphaned_support_remarks(caplog, wet_run):
    fake_content_type = ContentType.objects.create(app_label="non_existing_app", model="non_existing_model")

    existing_application = JobApplicationFactory()
    existing_user = existing_application.sender
    user_content_type = ContentType.objects.get_for_model(existing_user.__class__)
    application_content_type = ContentType.objects.get_for_model(existing_application.__class__)

    PkSupportRemark.objects.create(remark="test", content_type_id=user_content_type.pk, object_id=existing_user.pk)
    PkSupportRemark.objects.create(
        remark="test", content_type_id=user_content_type.pk, object_id=existing_user.pk + 9999
    )
    PkSupportRemark.objects.create(remark="test", content_type_id=fake_content_type.pk, object_id=9999)

    UUIDSupportRemark.objects.create(
        remark="test", content_type_id=application_content_type.pk, object_id=existing_application.pk
    )
    UUIDSupportRemark.objects.create(
        remark="test", content_type_id=application_content_type.pk, object_id=uuid.uuid4()
    )
    UUIDSupportRemark.objects.create(remark="test", content_type_id=fake_content_type.pk, object_id=uuid.uuid4())

    call_command("purge_orphaned_support_remarks", wet_run=wet_run)
    expected_logs = [
        (
            "SupportRemark objects linked to non existing model non_existing_app.non_existing_model. "
            "Please run remove_stale_contenttypes --include-stale-apps command for cleanup."
        ),
        "Deleted count=1 obsolete PkSupportRemark remarks linked to users.User",
        "Deleted count=1 obsolete UUIDSupportRemark remarks linked to job_applications.JobApplication",
    ]
    if not wet_run:
        expected_logs = (
            ["Command launched with wet_run=False"]
            + expected_logs
            + ["Setting transaction to be rollback as wet_run=False"]
        )
    assert caplog.messages[:-1] == expected_logs
    assert caplog.messages[-1].startswith(
        "Management command itou.utils.management.commands.purge_orphaned_support_remarks succeeded in"
    )
    assert PkSupportRemark.objects.count() == 2 if wet_run else 3
    assert UUIDSupportRemark.objects.count() == 2 if wet_run else 3
