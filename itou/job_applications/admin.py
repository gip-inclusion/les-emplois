import uuid

from django.contrib import admin, messages
from django.db.models import Q
from django.urls import reverse
from django.utils.safestring import mark_safe

from itou.employee_record import models as employee_record_models
from itou.job_applications import models
from itou.job_applications.admin_forms import JobApplicationAdminForm
from itou.job_applications.enums import Origin
from itou.users.models import User
from itou.utils.admin import UUIDSupportRemarkInline, get_admin_view_link
from itou.utils.templatetags.str_filters import pluralizefr


class TransitionLogInline(admin.TabularInline):
    model = models.JobApplicationTransitionLog
    extra = 0
    raw_id_fields = ("user",)
    can_delete = False
    readonly_fields = ("transition", "from_state", "to_state", "user", "timestamp")

    def has_add_permission(self, request, obj=None):
        return False


class PriorActionInline(admin.TabularInline):
    model = models.PriorAction
    extra = 0
    can_delete = False
    readonly_fields = ("action", "dates")
    verbose_name_plural = "actions préalable à l'embauche"

    def has_add_permission(self, request, obj=None):
        return False


class JobsInline(admin.TabularInline):
    model = models.JobApplication.selected_jobs.through
    verbose_name_plural = "fiches de poste"
    extra = 1
    raw_id_fields = ("siaejobdescription",)


class ManualApprovalDeliveryRequiredFilter(admin.SimpleListFilter):
    title = "délivrance manuelle de PASS IAE requise"
    parameter_name = "manual_approval_delivery_required"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"),)

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.manual_approval_delivery_required()
        return queryset


@admin.register(models.JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    form = JobApplicationAdminForm
    list_display = ("pk", "job_seeker", "state", "sender_kind", "created_at")
    show_full_result_count = False
    raw_id_fields = (
        "job_seeker",
        "eligibility_diagnosis",
        "geiq_eligibility_diagnosis",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
        "approval",
        "transferred_by",
        "transferred_from",
    )
    list_filter = (
        ManualApprovalDeliveryRequiredFilter,
        "sender_kind",
        "state",
        "approval_number_sent_by_email",
        "approval_delivery_mode",
        "sender_prescriber_organization__is_authorized",
        "to_siae__department",
        "origin",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "approval_number_sent_at",
        "approval_manually_delivered_by",
        "approval_manually_refused_by",
        "approval_manually_refused_at",
        "transferred_by",
        "transferred_at",
        "transferred_from",
        "origin",
    )
    inlines = (JobsInline, PriorActionInline, TransitionLogInline, UUIDSupportRemarkInline)

    fieldsets = [
        (
            "Candidature",
            {
                "fields": [
                    "state",
                    "job_seeker",
                    "to_siae",
                    "sender_kind",
                    "sender",
                    "sender_siae",
                    "sender_prescriber_organization",
                    "message",
                    "resume_link",
                    "refusal_reason",
                    "answer",
                    "answer_to_prescriber",
                    "hiring_start_at",
                    "hiring_end_at",
                    "hidden_for_siae",
                    "create_employee_record",
                ]
            },
        ),
        (
            "IAE",
            {
                "fields": [
                    "eligibility_diagnosis",
                    "hiring_without_approval",
                    "approval",
                    "approval_delivery_mode",
                    "approval_number_sent_by_email",
                    "approval_number_sent_at",
                    "approval_manually_delivered_by",
                    "approval_manually_refused_by",
                    "approval_manually_refused_at",
                ]
            },
        ),
        (
            "GEIQ",
            {
                "fields": [
                    "geiq_eligibility_diagnosis",
                    "prehiring_guidance_days",
                    "nb_hours_per_week",
                    "contract_type",
                    "contract_type_details",
                    "qualification_type",
                    "qualification_level",
                    "planned_training_hours",
                    "inverted_vae_contract",
                ]
            },
        ),
        (
            "Audit",
            {
                "fields": [
                    "origin",
                    "transferred_at",
                    "transferred_by",
                    "transferred_from",
                    "created_at",
                    "updated_at",
                ]
            },
        ),
    ]

    def get_search_fields(self, request):
        search_fields = []
        search_term = request.GET.get("q", "").strip()
        try:
            uuid.UUID(search_term)
        except (TypeError, ValueError):
            pass
        else:
            search_fields.append("pk__exact")
        siren_length = 9
        siret_length = 14
        if search_term.isdecimal() and len(search_term) in [siren_length, siret_length]:
            search_fields.append("to_siae__siret__startswith")

        # Without search_fields, the search bar is hidden.
        # Provide a dummy value that’s quick to search, in order not to slow
        # down relevant expensive searches that are added dynamically.
        return search_fields or ["state__startswith"]

    def get_search_results(self, request, queryset, search_term):
        if "@" in search_term:
            # Assume an email address is provided.
            # Instead of joining the User table twice (sender and job seeker),
            # lookup the user first (using the DB index), then use ForeignKey
            # indices to retrieve the corresponding job applications faster.
            #
            # Specifying user__email in the search_fields adds approximately
            # 2 seconds per field (so 4 seconds in total) to the query. This hack
            # allows answering the question in a few ms.
            try:
                user = User.objects.get(email=search_term)
            except User.DoesNotExist:
                pass
            else:
                return queryset.filter(Q(job_seeker=user) | Q(sender=user)), False
        return super().get_search_results(request, queryset, search_term)

    @admin.action(description="Créer une fiche salarié pour les candidatures sélectionnées")
    def create_employee_record(self, request, queryset):
        created, ignored = [], []

        for job_application in queryset:
            if job_application.employee_record.for_siae(job_application.to_siae).exists():
                ignored.append(job_application)
                continue

            try:
                employee_record = employee_record_models.EmployeeRecord.from_job_application(
                    job_application, clean=False
                )
                employee_record.save()
            except Exception as ex:
                messages.error(request, f"{job_application.pk} : {ex}")
            else:
                created.append(employee_record)

        if created:
            s = pluralizefr(created)
            links = ", ".join(get_admin_view_link(er) for er in created)
            messages.success(request, mark_safe(f"{len(created)} fiche{s} salarié{s} créée{s} : {links}"))
        if ignored:
            s = pluralizefr(ignored)
            links = ", ".join(get_admin_view_link(ja) for ja in ignored)
            messages.warning(request, mark_safe(f"{len(ignored)} candidature{s} ignorée{s} : {links}"))

    actions = [create_employee_record]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.origin = Origin.ADMIN

        super().save_model(request, obj, form, change)

    def get_form(self, request, obj=None, **kwargs):
        """
        Override a field's `help_text` to display a link to the PASS IAE delivery interface.
        The field is arbitrarily chosen between `approval_*` fields.
        """
        if obj and obj.manual_approval_delivery_required:
            url = reverse("admin:approvals_approval_manually_add_approval", args=[obj.pk])
            text = "Délivrer un PASS IAE dans l'admin"
            help_texts = {"approval_manually_delivered_by": mark_safe(f'<a href="{url}">{text}</a>')}
            kwargs.update({"help_texts": help_texts})
        return super().get_form(request, obj, **kwargs)


@admin.register(models.JobApplicationTransitionLog)
class JobApplicationTransitionLogAdmin(admin.ModelAdmin):
    actions = None
    date_hierarchy = "timestamp"
    list_display = ("job_application", "transition", "from_state", "to_state", "user", "timestamp")
    list_filter = ("transition",)
    list_select_related = ("job_application", "user")
    raw_id_fields = ("job_application", "user")
    readonly_fields = ("job_application", "transition", "from_state", "to_state", "user", "timestamp")
    search_fields = ("transition", "user__username", "job_application__pk")
