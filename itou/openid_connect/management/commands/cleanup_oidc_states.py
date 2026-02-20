from django.template.defaultfilters import pluralize

from itou.openid_connect.france_connect.models import FranceConnectState
from itou.openid_connect.pe_connect.models import PoleEmploiConnectState
from itou.openid_connect.pro_connect.models import ProConnectState
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = "Cleanup OIDC states."

    ATOMIC_HANDLE = False

    def handle(self, *args, **kwargs):
        for model in (FranceConnectState, PoleEmploiConnectState, ProConnectState):
            count, _ = model.objects.cleanup()
            self.logger.info(f"Deleted {count} obsolete {model.__name__}{pluralize(count)}")
