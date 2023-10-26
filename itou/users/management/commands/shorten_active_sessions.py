from importlib import import_module

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone

from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """Shorten all active sessions to let them alive for only one more hour.

    Any currently active user will be able to continue wotking on our website,
    but all offline users will have to login again.
    """

    def handle(self, **options):
        engine = import_module(settings.SESSION_ENGINE)
        new_expire = timezone.now() + relativedelta(hours=1)
        active_sessions_qs = engine.SessionStore.get_model_class().objects.filter(expire_date__gte=new_expire)
        self.stdout.write(f"Found {len(active_sessions_qs)} active sessions to shorten")
        active_sessions_qs.update(expire_date=new_expire)
