import datetime

from dateutil.relativedelta import relativedelta

from django.contrib import admin
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ugettext as _

from itou.approvals import models
from itou.job_applications.models import JobApplication


class IsValidFilter(admin.SimpleListFilter):
    title = _("En cours de validité")
    parameter_name = "is_valid"

    def lookups(self, request, model_admin):
        return (("yes", _("Oui")), ("no", _("Non")))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.valid()
        if value == "no":
            return queryset.invalid()
        return queryset


@admin.register(models.Approval)
class ApprovalAdmin(admin.ModelAdmin):
    actions = ("send_number_by_email",)
    list_display = (
        "id",
        "number",
        "user",
        "start_at",
        "end_at",
        "is_valid",
        "number_sent_by_email",
    )
    search_fields = ("number", "user__first_name", "user__last_name")
    list_filter = ("number_sent_by_email", IsValidFilter)
    list_display_links = ("id", "number")
    raw_id_fields = ("user", "job_application", "created_by")
    readonly_fields = ("created_at", "created_by", "number_sent_by_email")
    date_hierarchy = "start_at"

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def is_valid(self, obj):
        return obj.is_valid

    is_valid.boolean = True
    is_valid.short_description = _("En cours de validité")

    def add_view(self, request, form_url="", extra_context=None):
        """
        Prepopulate form fields with calculated data.
        """
        g = request.GET.copy()

        # Prepopulate `number`.
        job_application = JobApplication.objects.filter(
            id=g.get("job_application")
        ).first()
        date_of_hiring = job_application.date_of_hiring if job_application else None
        g.update({"number": self.model.get_next_number(date_of_hiring=date_of_hiring)})

        # Prepopulate `start_at` and `end_at`.
        start_at = g.get("start_at")
        if start_at:
            start_at = datetime.datetime.strptime(start_at, "%d/%m/%Y").date()
            end_at = start_at + relativedelta(years=2) - relativedelta(days=1)
            g.update({"start_at": start_at, "end_at": end_at})

        request.GET = g

        return super().add_view(request, form_url, extra_context=extra_context)

    def send_number_by_email(self, request, queryset):
        for approval in queryset:
            if approval.number_sent_by_email:
                message = _(f"{approval.number} - Email non envoyé : déjà envoyé.")
                messages.warning(request, message)
                continue
            try:
                approval.send_number_by_email()
                approval.number_sent_by_email = True
                approval.save()
            except RuntimeError:
                message = _(
                    f"{approval.number} - Email non envoyé : impossible de déterminer "
                    f" le destinataire (candidature inconnue)."
                )
                messages.warning(request, message)

    send_number_by_email.short_description = _("Envoyer le numéro par email")


@admin.register(models.PoleEmploiApproval)
class PoleEmploiApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "number",
        "first_name",
        "last_name",
        "birth_name",
        "start_at",
        "end_at",
        "is_valid",
    )
    search_fields = ("number", "first_name", "last_name", "birth_name")
    list_filter = (IsValidFilter,)
    date_hierarchy = "start_at"

    def is_valid(self, obj):
        return obj.is_valid

    is_valid.boolean = True
    is_valid.short_description = _("En cours de validité")
