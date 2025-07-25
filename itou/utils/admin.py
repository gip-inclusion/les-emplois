from unittest import mock

from django import forms
from django.contrib.admin import ModelAdmin, StackedInline, TabularInline
from django.contrib.auth import get_permission_codename
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


def get_structure_view_link(structure, display_attr="name"):
    format_string = "{link}"
    format_kwargs = {"link": get_admin_view_link(structure, content=getattr(structure, display_attr))}
    if hasattr(structure, "siret"):
        format_string += " — SIRET {siret}"
        format_kwargs["siret"] = structure.siret
    format_string += " ({kind})"
    format_kwargs["kind"] = structure.kind
    format_string += " — PK: {pk}"
    format_kwargs["pk"] = structure.pk
    return format_html(format_string, **format_kwargs)


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

    def check_inconsistencies(self, request, queryset, message_when_no_inconsistency=True):
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
        elif message_when_no_inconsistency:
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

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self.check_inconsistencies(
            request, obj._meta.default_manager.filter(pk=obj.pk), message_when_no_inconsistency=False
        )


class ItouModelMixin:
    # Add save buttons on top of each change forms by default
    save_on_top = True
    get_object_ignored_prefetch_related_fields = set()  # Remove automatically added (but useless) fields
    get_object_extra_select_related_fields = set()  # Add extra fields to select_related (like OneToOne relations)

    def _get_queryset_with_relations(self, request):
        select_related_fields, prefetch_related_fields = set(), set()
        for field in self.model._meta.get_fields():
            if not field.is_relation or field.auto_created:
                continue

            if field.many_to_many or isinstance(field, GenericRelation):
                prefetch_related_fields.add(field.name)
            else:
                select_related_fields.add(field.name)

        prefetch_related_fields -= self.get_object_ignored_prefetch_related_fields
        select_related_fields |= self.get_object_extra_select_related_fields
        return (
            super()
            .get_queryset(request)
            .select_related(*select_related_fields)
            .prefetch_related(*prefetch_related_fields)
            .defer(None)  # Clear possible deferred fields
        )

    def get_object(self, request, object_id, from_field=None):
        # Eager-loading all relations, but only when editing one object because `list_select_related` exists
        with mock.patch.object(self, "get_queryset", self._get_queryset_with_relations):
            return super().get_object(request, object_id, from_field)


class ItouModelAdmin(ItouModelMixin, ModelAdmin):
    pass


def add_support_remark_to_obj(obj, text):
    obj_content_type = ContentType.objects.get_for_model(obj)
    try:
        remark = PkSupportRemark.objects.filter(content_type=obj_content_type, object_id=obj.pk).get()
    except PkSupportRemark.DoesNotExist:
        PkSupportRemark.objects.create(content_type=obj_content_type, object_id=obj.pk, remark=text)
    else:
        remark.remark += "\n" + text
        remark.save(update_fields=("remark",))


class ReadonlyMixin:
    def has_add_permission(self, *args, **kwargs):
        return False

    def has_change_permission(self, *args, **kwargs):
        return False

    def has_delete_permission(self, *args, **kwargs):
        return False


class TransitionLogMixin(ReadonlyMixin):
    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return False

        modified_object = obj.get_modified_object()
        codename = get_permission_codename("delete", modified_object._meta)
        return request.user.has_perm(f"{modified_object._meta.app_label}.{codename}")


class CreatedOrUpdatedByMixin:
    def save_model(self, request, obj, form, change):
        attr = "updated_by" if change else "created_by"
        if hasattr(obj, attr):
            setattr(obj, attr, request.user)
        super().save_model(request, obj, form, change)


class ChooseFieldsToTransfer(forms.Form):
    fields_to_transfer = forms.MultipleChoiceField(
        choices=[],
        required=True,
        label="Choisissez les objets à transférer",
        widget=forms.CheckboxSelectMultiple(),
    )

    def __init__(self, *args, fields_choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fields_to_transfer"].choices = fields_choices
