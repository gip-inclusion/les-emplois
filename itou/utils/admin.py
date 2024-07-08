from unittest import mock

from django.contrib.admin import ModelAdmin, StackedInline, TabularInline
from django.contrib.contenttypes.admin import GenericStackedInline
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.forms import fields as gis_fields
from django.contrib.messages import WARNING
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from itou.utils.models import PkSupportRemark, UUIDSupportRemark
from itou.utils.templatetags.str_filters import pluralizefr
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


class ItouTabularInline(TabularInline):
    list_select_related = None

    def get_queryset(self, request):
        select_related_fields = set(self.list_select_related or [])
        prefetch_related_fields = set()
        for field in {field for field in self.model._meta.get_fields() if field.name in self.get_fields(request)}:
            if not field.is_relation or field.auto_created or field.many_to_many:
                continue
            if isinstance(field, GenericRelation):
                prefetch_related_fields.add(field.name)
            else:
                select_related_fields.add(field.name)

        return (
            super()
            .get_queryset(request)
            .select_related(*select_related_fields)
            .prefetch_related(*prefetch_related_fields)
        )


class ItouStackedInline(StackedInline, ItouTabularInline):
    pass


class InconsistencyCheckMixin:
    INCONSISTENCY_CHECKS = []

    def check_inconsistencies(self, request, queryset):
        inconsistencies = {}
        for title, check in self.INCONSISTENCY_CHECKS:
            for item in check(queryset):
                inconsistencies.setdefault(item, []).append(title)
        if inconsistencies:
            s = pluralizefr(len(inconsistencies))
            title = f"{len(inconsistencies)} objet{s} incohérent{s}"
            self.message_user(
                request,
                format_html(
                    "{}: <ul>{}</ul>",
                    title,
                    format_html_join(
                        "",
                        '<li class="warning">{}: {}</li>',
                        [
                            (
                                get_admin_view_link(item, content=f"{item._meta.verbose_name} - {item.pk}"),
                                ", ".join(item_inconsistencies),
                            )
                            for item, item_inconsistencies in inconsistencies.items()
                        ],
                    ),
                ),
                level=WARNING,
            )
        else:
            self.message_user(request, "Aucune incohérence trouvée")

    def get_actions(self, request):
        actions = super().get_actions(request)
        if self.INCONSISTENCY_CHECKS:
            actions["check_inconsistencies"] = (
                InconsistencyCheckMixin.check_inconsistencies,
                "check_inconsistencies",
                "Vérifier la cohérence des objets",
            )
        return actions


class ItouModelAdmin(ModelAdmin):
    # Add save buttons on top of each change forms by default
    save_on_top = True

    def _get_queryset_with_relations(self, request):
        select_related_fields, prefetch_related_fields = set(), set()
        for field in self.model._meta.get_fields():
            if not field.is_relation or field.auto_created:
                continue

            if field.many_to_many or isinstance(field, GenericRelation):
                prefetch_related_fields.add(field.name)
            else:
                select_related_fields.add(field.name)

        return (
            super()
            .get_queryset(request)
            .select_related(*select_related_fields)
            .prefetch_related(*prefetch_related_fields)
        )

    def get_object(self, request, object_id, from_field=None):
        # Eager-loading all relations, but only when editing one object because `list_select_related` exists
        with mock.patch.object(self, "get_queryset", self._get_queryset_with_relations):
            return super().get_object(request, object_id, from_field)


def add_support_remark_to_obj(obj, text):
    obj_content_type = ContentType.objects.get_for_model(obj)
    try:
        remark = PkSupportRemark.objects.filter(content_type=obj_content_type, object_id=obj.pk).get()
    except PkSupportRemark.DoesNotExist:
        PkSupportRemark.objects.create(content_type=obj_content_type, object_id=obj.pk, remark=text)
    else:
        remark.remark += "\n" + text
        remark.save(update_fields=("remark",))
