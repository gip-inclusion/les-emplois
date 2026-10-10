from django import forms
from django.contrib import admin, messages
from django.contrib.admin import widgets
from django.db.models import Count
from django.forms import BaseInlineFormSet, ValidationError

from itou.utils.admin import ChooseFieldsToTransfer, FakeRelForRawIdWidget, ItouModelAdmin, ItouTabularInline


class MembersInlineFormSet(BaseInlineFormSet):
    def __init__(self, *args, acting_user, **kwargs):
        self.acting_user = acting_user
        return super().__init__(*args, **kwargs)

    def add_fields(self, form, index):
        super().add_fields(form, index)
        # BaseModelFormSet uses the default manager, which excludes inactive users.
        # https://github.com/django/django/blob/f11fb107662662f53a6ec45bbd36a06c6c4c05ea/django/forms/models.py#L1003
        form.fields[self.model._meta.pk.name].queryset = self.queryset

    def _handle_save(self, form):
        if form.instance.pk:
            membership = form.instance
            if "is_admin" in form.changed_data:
                self.instance.set_admin_role(
                    membership,
                    form.cleaned_data["is_admin"],
                    updated_by=self.acting_user,
                )
            if "is_active" in form.changed_data:
                if form.cleaned_data["is_active"]:
                    self.instance.add_or_activate_membership(
                        form.cleaned_data["user"],
                        force_admin=form.cleaned_data["is_admin"],
                    )
                else:
                    # This will also remove admin role, do we call set_admin_role before to send the email ?
                    self.instance.deactivate_membership(
                        membership,
                        updated_by=self.acting_user,
                    )
        else:
            membership = self.instance.add_or_activate_membership(
                form.cleaned_data["user"],
                force_admin=form.cleaned_data["is_admin"],
            )
        return membership

    def save_new(self, form, commit=True):
        if commit:
            return self._handle_save(form)
        return super().save_new(form, commit=commit)

    def save_existing(self, form, obj, commit=True):
        if commit:
            return self._handle_save(form)
        return super().save_existing(form, obj, commit=commit)


class MembersInline(ItouTabularInline):
    # Remember to specify the model in child class. Example:
    # model = models.Company.members.through
    extra = 0
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at", "updated_by", "joined_at")
    ordering = ("user__last_name", "user__first_name", "joined_at")
    formset = MembersInlineFormSet

    def get_queryset(self, request):
        queryset = self.model.include_inactive.all()
        ordering = self.get_ordering(request)
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset

    def has_delete_permission(self, *args, **kwargs):
        return False


class HasMembersFilter(admin.SimpleListFilter):
    title = "A des membres"
    parameter_name = "has_members"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(_member_count__gt=0)
        if value == "no":
            return queryset.exclude(_member_count__gt=0)
        return queryset


class OrganizationAdmin(ItouModelAdmin):
    @admin.display(ordering="_member_count")
    def member_count(self, obj):
        return obj._member_count

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_member_count=Count("members", distinct=True))

    def get_formset_kwargs(self, request, obj, inline, prefix):
        kwargs = super().get_formset_kwargs(request, obj, inline, prefix)
        if isinstance(inline, MembersInline):
            kwargs["acting_user"] = request.user
        return kwargs

    def save_related(self, request, form, formsets, change):
        had_admin = change and form.instance.active_admin_members.exists()
        super().save_related(request, form, formsets, change)
        if had_admin:
            active_memberships = form.instance.memberships.all()
            if active_memberships and not any(membership.is_admin for membership in active_memberships):
                messages.warning(
                    request,
                    (
                        "Vous venez de supprimer le dernier administrateur de la structure. "
                        "Les membres restants risquent de solliciter le support."
                    ),
                )


class SelectTargetOrgForm(forms.Form):
    def __init__(self, *args, from_org, org_model_label, admin_site, **kwargs):
        super().__init__(*args, **kwargs)
        model = from_org.__class__
        self.from_org = from_org
        self.org_model_label = org_model_label
        self.fields["to_org"] = forms.ModelChoiceField(
            model.objects.all(),
            required=True,
            label=f"Choisissez l’{self.org_model_label} cible",
            widget=widgets.ForeignKeyRawIdWidget(FakeRelForRawIdWidget(model), admin_site),
        )

    def clean_to_org(self):
        to_org = self.cleaned_data["to_org"]
        if to_org.pk == self.from_org.pk:
            raise ValidationError(f"L’{self.org_model_label} cible doit être différente de celle d’origine")
        return to_org


class OrgChooseFieldsToTransfer(ChooseFieldsToTransfer):
    disable_from_org = forms.BooleanField(required=False, initial=True)

    def __init__(self, org_model_label, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["disable_from_org"].label = f"Désactiver l’{org_model_label} source"
