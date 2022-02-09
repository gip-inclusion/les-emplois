from django.contrib.contenttypes.admin import GenericStackedInline

from itou.utils.models import SupportRemark


class SupportRemarkInline(GenericStackedInline):
    model = SupportRemark
    min_num = 0
    max_num = 1
    extra = 1
    can_delete = False
