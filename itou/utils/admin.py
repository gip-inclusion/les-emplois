from django.contrib.contenttypes.admin import GenericStackedInline

from itou.utils.models import PkSupportRemark, UUIDSupportRemark


class AbstractSupportRemarkInline(GenericStackedInline):
    min_num = 0
    max_num = 1
    extra = 1
    can_delete = False


class PkSupportRemarkInline(AbstractSupportRemarkInline):
    model = PkSupportRemark


class UUIDSupportRemarkInline(AbstractSupportRemarkInline):
    model = UUIDSupportRemark
