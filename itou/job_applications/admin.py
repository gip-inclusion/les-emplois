import copy
import uuid

import xworkflows
from django.contrib import admin, messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.safestring import mark_safe

from itou.employee_record import models as employee_record_models
from itou.job_applications import models
from itou.job_applications.admin_forms import JobApplicationAdminForm
from itou.job_applications.enums import Origin
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.users.models import User
from itou.utils.admin import (
    InconsistencyCheckMixin,
    ItouModelAdmin,
    ItouStackedInline,
    ItouTabularInline,
    ReadonlyMixin,
    TransitionLogMixin,
    UUIDSupportRemarkInline,
    get_admin_view_link,
)
from itou.utils.templatetags.str_filters import pluralizefr


class TransitionLogInline(ReadonlyMixin, ItouTabularInline):
    model = models.JobApplicationTransitionLog
    extra = 0
    raw_id_fields = ("user",)
    readonly_fields = ("transition", "from_state", "to_state", "user", "timestamp", "target_company")


class PriorActionInline(ReadonlyMixin, ItouTabularInline):
    model = models.PriorAction
    extra = 0
    readonly_fields = ("action", "dates")
    verbose_name_plural = "actions préalable à l'embauche"


class JobsInline(ItouTabularInline):
    model = models.JobApplication.selected_jobs.through
    verbose_name_plural = "fiches de poste"
    extra = 1
    raw_id_fields = ("jobdescription",)


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


class FromAuthorizedPrescriberOrganizationFilter(admin.SimpleListFilter):
    title = "habilitation"
    parameter_name = "is_authorized"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(
                sender_prescriber_organization__authorization_status=PrescriberAuthorizationStatus.VALIDATED
            )
        if value == "no":
            return queryset.exclude(
                sender_prescriber_organization__authorization_status=PrescriberAuthorizationStatus.VALIDATED
            )
        return queryset


class EmployeeRecordInline(ReadonlyMixin, ItouStackedInline):
    model = employee_record_models.EmployeeRecord
    extra = 0
    fields = ("link",)
    readonly_fields = ("link",)

    @admin.display(description="situation fiche salarié")
    def link(self, obj):
        return get_admin_view_link(
            obj,
            content=mark_safe(f"<b>{obj.get_status_display()} (ID: {obj.pk})</b>"),
        )


@admin.register(models.JobApplication)
class JobApplicationAdmin(InconsistencyCheckMixin, ItouModelAdmin):
    form = JobApplicationAdminForm
    list_display = ("pk", "job_seeker", "state", "sender_kind", "created_at")
    show_full_result_count = False
    raw_id_fields = (
        "job_seeker",
        "eligibility_diagnosis",
        "geiq_eligibility_diagnosis",
        "hired_job",
        "sender",
        "sender_company",
        "sender_prescriber_organization",
        "to_company",
        "approval",
        "transferred_by",
        "transferred_from",
        "resume",
    )
    list_filter = (
        ManualApprovalDeliveryRequiredFilter,
        "sender_kind",
        "state",
        "approval_number_sent_by_email",
        "approval_delivery_mode",
        FromAuthorizedPrescriberOrganizationFilter,
        "to_company__department",
        "origin",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "processed_at",
        "archived_at",
        "archived_by",
        "approval_number_sent_at",
        "approval_manually_delivered_by",
        "approval_manually_refused_by",
        "approval_manually_refused_at",
        "message",
        "answer",
        "answer_to_prescriber",
        "transferred_by",
        "transferred_at",
        "transferred_from",
        "origin",
        "state",
        "diagoriente_invite_sent_at",
        "contract_type_details",
    )
    inlines = (JobsInline, PriorActionInline, TransitionLogInline, UUIDSupportRemarkInline, EmployeeRecordInline)

    fieldsets = [
        (
            "Candidature",
            {
                "fields": [
                    "state",
                    "job_seeker",
                    "to_company",
                    "message",
                    "resume",
                    "refusal_reason",
                    "answer",
                    "answer_to_prescriber",
                    "hiring_start_at",
                    "hiring_end_at",
                    "hired_job",
                    "create_employee_record",
                ]
            },
        ),
        (
            "Origine",
            {
                "fields": [
                    "sender",
                    "sender_kind",
                    "sender_company",
                    "sender_prescriber_organization",
                ]
            },
        ),
        (
            "IAE",
            {
                "fields": [
                    "eligibility_diagnosis",
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
                    "processed_at",
                    "archived_at",
                    "archived_by",
                    "diagoriente_invite_sent_at",
                ]
            },
        ),
    ]
    change_form_template = "admin/job_applications/jobapplication_change_form.html"

    INCONSISTENCY_CHECKS = [
        (
            "Candidature liée au PASS IAE d'un autre candidat",
            lambda q: q.inconsistent_approval_user(),
        ),
        (
            "Candidature liée au diagnostic d'un autre candidat",
            lambda q: q.inconsistent_eligibility_diagnosis_job_seeker(),
        ),
        (
            "Candidature liée au diagnostic GEIQ d'un autre candidat",
            lambda q: q.inconsistent_geiq_eligibility_diagnosis_job_seeker(),
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
            search_fields.append("to_company__siret__startswith")

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
            if job_application.employee_record.for_asp_company(job_application.to_company).exists():
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

    def transition_error(self, request, error):
        message = None
        if error.args[0] == models.JobApplicationWorkflow.error_missing_eligibility_diagnostic:
            message = (
                "Un diagnostic d'éligibilité valide pour ce candidat "
                "et cette SIAE est obligatoire pour pouvoir créer un PASS IAE."
            )
        elif error.args[0] == models.JobApplicationWorkflow.error_missing_hiring_start_at:
            message = "Le champ 'Date de début du contrat' est obligatoire pour accepter une candidature"
        elif error.args[0] == models.JobApplicationWorkflow.error_wrong_eligibility_diagnosis:
            message = "Le diagnostic d'eligibilité n'est pas valide pour ce candidat et cette entreprise"
        self.message_user(request, message or error, messages.ERROR)
        return HttpResponseRedirect(request.get_full_path())

    def response_change(self, request, obj):
        """
        Override to add custom "actions" in `self.change_form_template` for:
        * processing the job application
        * accepting the job application
        * refusing the job application
        * reseting the job applciation
        """
        for transition in ["accept", "cancel", "reset", "process"]:
            if f"transition_{transition}" in request.POST:
                try:
                    getattr(obj, transition)(user=request.user)
                    # Stay on same page
                    updated_request = copy.deepcopy(request.POST)
                    updated_request.update({"_continue": ["please"]})
                    request.POST = updated_request
                except xworkflows.AbortTransition as e:
                    return self.transition_error(request, e)

        return super().response_change(request, obj)


@admin.register(models.JobApplicationTransitionLog)
class JobApplicationTransitionLogAdmin(TransitionLogMixin, ItouModelAdmin):
    actions = None
    date_hierarchy = "timestamp"
    list_display = ("job_application", "transition", "from_state", "to_state", "user", "timestamp")
    list_filter = ("transition",)
    list_select_related = ("job_application", "user")
    raw_id_fields = ("job_application", "user")
    readonly_fields = ("job_application", "transition", "from_state", "to_state", "user", "timestamp")
    search_fields = ("transition", "user__username", "job_application__pk")
