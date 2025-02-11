from django.contrib import admin, messages
from django.db.models import Count
from django.forms import BaseInlineFormSet

from itou.utils.admin import ItouModelAdmin, ItouTabularInline


class MembersInlineFormSet(BaseInlineFormSet):
    def __init__(self, *args, acting_user, **kwargs):
        self.acting_user = acting_user
        return super().__init__(*args, **kwargs)

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
    formset = MembersInlineFormSet

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
