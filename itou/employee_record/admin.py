import itertools

import xworkflows
from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

import itou.employee_record.models as models
from itou.companies import models as companies_models
from itou.employee_record.models import EmployeeRecordUpdateNotification
from itou.utils.admin import ItouModelAdmin, ItouTabularInline, ReadonlyMixin, get_admin_view_link
from itou.utils.templatetags.str_filters import pluralizefr


class EmployeeRecordUpdateNotificationInline(ReadonlyMixin, ItouTabularInline):
    model = models.EmployeeRecordUpdateNotification

    fields = (
        "created_at",
        "status",
        "asp_batch_file",
        "asp_batch_line_number",
    )

    readonly_fields = fields
    fk_name = "employee_record"

    show_change_link = True
    extra = 0


class EmployeeRecordAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "financial_annex" in self.fields:
            self.fields["financial_annex"].required = False
            self.fields["financial_annex"].queryset = companies_models.SiaeFinancialAnnex.objects.filter(
                convention=self.instance.job_application.to_company.convention
            ).order_by("-number")


class ASPExchangeInformationAdminMixin:
    @admin.display(description="dernier mouvement")
    def last_movement(self, obj):
        movement = sorted(
            itertools.chain([obj], obj.update_notifications.all()), key=lambda e: max(e.created_at, e.updated_at)
        ).pop()
        return get_admin_view_link(movement, content=str(movement))

    @admin.display(description="dernier envoi")
    def last_exchange(self, obj):
        exchanges = [
            exchange for exchange in itertools.chain([obj], obj.update_notifications.all()) if exchange.asp_batch_file
        ]
        if not exchanges:
            return "Aucun"

        last_exchange = sorted(exchanges, key=lambda e: e.asp_batch_file).pop()
        return get_admin_view_link(last_exchange, content=str(last_exchange))

    @admin.display(description="données SIAE envoyées")
    def company_data_sent(self, obj):
        if not obj.archived_json:
            return self.get_empty_value_display()

        siret = obj.archived_json["siret"]
        measure = obj.archived_json["mesure"]
        return f"{siret} ({measure})"

    @admin.display(description="données candidat envoyées")
    def user_data_sent(self, obj):
        if not obj.archived_json:
            return self.get_empty_value_display()

        firstname = obj.archived_json["personnePhysique"]["prenom"]
        lastname = obj.archived_json["personnePhysique"]["nomUsage"]
        id_itou = obj.archived_json["personnePhysique"]["idItou"]
        return f"{firstname}, {lastname} ({id_itou})"

    @admin.display(description="données PASS IAE envoyées")
    def approval_data_sent(self, obj):
        if not obj.archived_json:
            return self.get_empty_value_display()

        number = obj.archived_json["personnePhysique"]["passIae"]
        start = obj.archived_json["personnePhysique"]["passDateDeb"]
        end = obj.archived_json["personnePhysique"]["passDateFin"]
        return f"{number} ({start} – {end})"


class EmployeeRecordTransitionLogInline(ReadonlyMixin, ItouTabularInline):
    model = models.EmployeeRecordTransitionLog
    extra = 0
    fields = (
        "transition",
        "from_state",
        "to_state",
        "user",
        "timestamp",
        "asp_processing_code",
        "asp_processing_label",
        "asp_batch_file",
    )
    raw_id_fields = ("user",)


@admin.register(models.EmployeeRecord)
class EmployeeRecordAdmin(ASPExchangeInformationAdminMixin, ItouModelAdmin):
    form = EmployeeRecordAdminForm

    @admin.action(description="Planifier une notification de changement 'PASS IAE' pour ces fiches salarié")
    def schedule_approval_update_notification(self, request, queryset):
        total_created = 0
        for employee_record in queryset:
            _, created = models.EmployeeRecordUpdateNotification.objects.update_or_create(
                employee_record=employee_record,
                status=models.NotificationStatus.NEW,
                defaults={"updated_at": timezone.now},
            )
            total_created += int(created)

        if total_created:
            s = pluralizefr(total_created)
            messages.success(request, f"{total_created} notification{s} planifiée{s}")

        total_updated = len(queryset) - total_created
        if total_updated:
            s = pluralizefr(total_updated)
            messages.success(request, f"{total_updated} notification{s} mise{s} à jour")

    actions = [
        schedule_approval_update_notification,
    ]

    inlines = (EmployeeRecordUpdateNotificationInline, EmployeeRecordTransitionLogInline)

    list_display = (
        "pk",
        "created_at",
        "updated_at",
        "approval_number",
        "siret",
        "asp_processing_code",
        "status",
    )

    list_filter = (
        "status",
        "processed_as_duplicate",
    )

    search_fields = (
        "siret",
        "approval_number",
        "asp_batch_file",
    )

    raw_id_fields = ("job_application",)

    readonly_fields = (
        "pk",
        "status",
        "created_at",
        "updated_at",
        "processed_at",
        "approval_number_link",
        "job_application",
        "job_seeker_link",
        "job_seeker_profile_link",
        "siret",
        "asp_id",
        "asp_measure",
        "asp_processing_type",
        "asp_batch_file",
        "asp_batch_line_number",
        "asp_processing_code",
        "asp_processing_label",
        "archived_json",
        # Custom admin fields
        "last_movement",
        "last_exchange",
        "company_data_sent",
        "user_data_sent",
        "approval_data_sent",
    )
    show_full_result_count = False

    fieldsets = (
        (
            "Aide",
            {
                "fields": (
                    "last_movement",
                    "last_exchange",
                )
            },
        ),
        (
            "Informations",
            {
                "fields": (
                    "pk",
                    "status",
                    "job_application",
                    "approval_number_link",
                    "job_seeker_link",
                    "job_seeker_profile_link",
                    "siret",
                    "asp_measure",
                    "asp_id",
                    "financial_annex",
                    "created_at",
                    "updated_at",
                    "processed_at",
                )
            },
        ),
        (
            "Traitement ASP",
            {
                "fields": (
                    "asp_processing_type",
                    "asp_batch_file",
                    "asp_batch_line_number",
                    "asp_processing_code",
                    "asp_processing_label",
                    "company_data_sent",
                    "user_data_sent",
                    "approval_data_sent",
                    "archived_json",
                )
            },
        ),
    )

    change_form_template = "admin/employee_records/employeerecord_change_form.html"

    @admin.display(description="numéro d'agrément")
    def approval_number_link(self, obj):
        if approval_number := obj.approval_number:
            url = reverse("admin:approvals_approval_change", args=(obj.job_application.approval_id,))
            return format_html('<a href="{}">{}</a>', url, approval_number)

    @admin.display(description="salarié")
    def job_seeker_link(self, obj):
        if job_seeker := obj.job_application.job_seeker:
            return get_admin_view_link(job_seeker, content=job_seeker)

        return self.get_empty_value_display()

    @admin.display(description="profil du salarié")
    def job_seeker_profile_link(self, obj):
        job_seeker_profile = obj.job_application.job_seeker.jobseeker_profile
        return get_admin_view_link(job_seeker_profile, content=f"Profil salarié ID:{job_seeker_profile.pk}")

    @admin.display(description="type de traitement")
    def asp_processing_type(self, obj):
        if obj.processed_as_duplicate:
            return "Intégrée par les emplois suite à une erreur 3436 (doublon PASS IAE/SIRET)"
        if obj.asp_processing_code == obj.ASP_PROCESSING_SUCCESS_CODE:
            return "Intégrée par l'ASP"
        return self.get_empty_value_display()

    def has_add_permission(self, request):
        return False

    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        # EmployeeRecordUpdateNotification() are readonly, but we don't want to block EmployeeRecord() deletion
        perms_needed.discard(EmployeeRecordUpdateNotification._meta.verbose_name)
        return deleted_objects, model_count, perms_needed, protected

    def response_change(self, request, obj):
        for transition in obj.status.transitions():
            if f"transition_{transition.name}" in request.POST:
                try:
                    getattr(obj, transition.name)(user=request.user)
                except xworkflows.AbortTransition as e:
                    self.message_user(request, e, messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

        return super().response_change(request, obj)

    def render_change_form(self, request, context, *, obj=None, **kwargs):
        if obj:
            system_transitions = {
                models.EmployeeRecordTransition.WAIT_FOR_ASP_RESPONSE,
                models.EmployeeRecordTransition.REJECT,
                models.EmployeeRecordTransition.PROCESS,
            }
            context.update(
                {
                    "available_transitions": [
                        transition
                        for transition in obj.status.transitions()
                        if getattr(obj, transition.name).is_available() and transition.name not in system_transitions
                    ]
                }
            )
        return super().render_change_form(request, context, **kwargs)


@admin.register(models.EmployeeRecordUpdateNotification)
class EmployeeRecordUpdateNotificationAdmin(ReadonlyMixin, ASPExchangeInformationAdminMixin, ItouModelAdmin):
    list_display = (
        "pk",
        "created_at",
        "updated_at",
        "asp_processing_code",
        "status",
    )

    list_filter = ("status",)

    raw_id_fields = ("employee_record",)

    readonly_fields = (
        "pk",
        "employee_record",
        "created_at",
        "updated_at",
        "asp_batch_file",
        "asp_batch_line_number",
        "asp_processing_code",
        "asp_processing_label",
        "archived_json",
        # Custom admin fields
        "company_data_sent",
        "user_data_sent",
        "approval_data_sent",
    )

    search_fields = [
        "employee_record__siret",
        "employee_record__approval_number",
        "asp_batch_file",
    ]

    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "pk",
                    "status",
                    "employee_record",
                    "created_at",
                    "updated_at",
                )
            },
        ),
        (
            "Traitement ASP",
            {
                "fields": (
                    "asp_batch_file",
                    "asp_batch_line_number",
                    "asp_processing_code",
                    "asp_processing_label",
                    "company_data_sent",
                    "user_data_sent",
                    "approval_data_sent",
                    "archived_json",
                )
            },
        ),
    )
