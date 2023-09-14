from itou.common_apps.address.base_insee_city_resolver import BaseInseeCityResolverCommand
from itou.users.enums import UserKind
from itou.users.models import User


class Command(BaseInseeCityResolverCommand):
    queryset = User.objects.filter(is_active=True, kind=UserKind.JOB_SEEKER)
