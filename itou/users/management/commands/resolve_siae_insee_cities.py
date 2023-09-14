from itou.common_apps.address.base_insee_city_resolver import BaseInseeCityResolverCommand
from itou.siaes.models import Siae


class Command(BaseInseeCityResolverCommand):
    queryset = Siae.objects.active()
