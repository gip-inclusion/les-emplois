from django.contrib.contenttypes.admin import GenericStackedInline
from django.contrib.gis.forms import fields as gis_fields
from django.urls import reverse
from django.utils.html import format_html

from itou.utils.models import PkSupportRemark, UUIDSupportRemark
from itou.utils.widgets import OSMWidget


def get_admin_view_link(obj, *, content=None, view="change"):
    url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_{view}", args=[obj.pk])
    return format_html('<a href="{}">{}</a>', url, content or obj.pk)


class AbstractSupportRemarkInline(GenericStackedInline):
    min_num = 0
    max_num = 1
    extra = 1
    can_delete = False


class PkSupportRemarkInline(AbstractSupportRemarkInline):
    model = PkSupportRemark


class UUIDSupportRemarkInline(AbstractSupportRemarkInline):
    model = UUIDSupportRemark


class ItouGISMixin:
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if isinstance(field, gis_fields.PointField):
            field.widget = OSMWidget(attrs={"map_width": 800, "map_height": 500, "CSP_NONCE": request.csp_nonce})
        return field
