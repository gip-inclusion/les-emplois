from importlib import import_module

from django.conf import settings
from django.utils import timezone

from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def handle(self, **options):
        engine = import_module(settings.SESSION_ENGINE)
        new_expire = timezone.now()
        expired = (
            engine.SessionStore.get_model_class()
            .objects.filter(expire_date__gte=new_expire)
            .update(expire_date=new_expire)
        )
        self.logger.info("Expired %d active sessions.", expired)
