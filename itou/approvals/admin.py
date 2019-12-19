import datetime

from dateutil.relativedelta import relativedelta

from django.contrib import admin
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ugettext as _

from itou.approvals import models


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
    list_filter = ("number_sent_by_email",)
    list_display_links = ("id", "number")
    raw_id_fields = ("user", "job_application", "created_by")
    readonly_fields = ("created_at", "created_by", "number_sent_by_email")

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
        Prepopulate the form with calculated data.
        """
        g = request.GET.copy()
        g.update({"number": self.model.get_next_number()})
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
