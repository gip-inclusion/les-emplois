from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.emails.models import Email


class TestExpireOldEmails:
    def test_dry_run(self, caplog):
        now = timezone.now()
        with freeze_time(now - timedelta(days=182)):
            old = Email.objects.create(to=["old@test.local"], subject="Old stuff", body_text="Old")
        with freeze_time(now - timedelta(days=181)):
            after_cutoff = Email.objects.create(to=["recent@test.local"], subject="Recent stuff", body_text="Recent")
        call_command("delete_old_emails")
        assert caplog.messages[0] == "Would delete 1 email"
        assertQuerySetEqual(Email.objects.all(), [after_cutoff, old])

    def test_wet_run(self, caplog):
        now = timezone.now()
        with freeze_time(now - timedelta(days=182)):
            Email.objects.create(to=["old@test.local"], subject="Old stuff", body_text="Old")
        with freeze_time(now - timedelta(days=181)):
            after_cutoff = Email.objects.create(to=["recent@test.local"], subject="Recent stuff", body_text="Recent")
        call_command("delete_old_emails", wet_run=True)
        assert caplog.messages[0] == "Deleted 1 email"
        assertQuerySetEqual(Email.objects.all(), [after_cutoff])
