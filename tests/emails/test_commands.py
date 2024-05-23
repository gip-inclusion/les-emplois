import io
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.emails.models import Email


class TestExpireOldEmails:
    def test_dry_run(self):
        now = timezone.now()
        with freeze_time(now - timedelta(days=365)):
            old = Email.objects.create(to=["old@test.local"], subject="Old stuff", body_text="Old")
        with freeze_time(now - timedelta(days=364)):
            after_cutoff = Email.objects.create(to=["recent@test.local"], subject="Recent stuff", body_text="Recent")
        with io.StringIO() as stdout:
            call_command("delete_old_emails", stdout=stdout)
            assert "Would delete 1 email." in stdout.getvalue()
        assertQuerySetEqual(Email.objects.all(), [after_cutoff, old])

    def test_wet_run(self):
        now = timezone.now()
        with freeze_time(now - timedelta(days=365)):
            Email.objects.create(to=["old@test.local"], subject="Old stuff", body_text="Old")
        with freeze_time(now - timedelta(days=364)):
            after_cutoff = Email.objects.create(to=["recent@test.local"], subject="Recent stuff", body_text="Recent")
        with io.StringIO() as stdout:
            call_command("delete_old_emails", stdout=stdout, wet_run=True)
            assert "Deleted 1 email." in stdout.getvalue()
        assertQuerySetEqual(Email.objects.all(), [after_cutoff])
