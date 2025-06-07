from pprint import pformat

from django.contrib import admin, messages
from django.contrib.admin.utils import display_for_value
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from itou.approvals.models import Approval
from itou.common_apps.organizations.admin import HasMembersFilter, MembersInline, OrganizationAdmin
from itou.companies import enums, models, transfer
from itou.companies.admin_forms import CompanyChooseFieldsToTransfer, SelectTargetCompanyForm
from itou.siae_evaluations.models import EvaluatedSiae
from itou.utils.admin import (
    CreatedOrUpdatedByMixin,
    ItouGISMixin,
    ItouModelAdmin,
    ItouTabularInline,
    PkSupportRemarkInline,
    ReadonlyMixin,
    add_support_remark_to_obj,
    get_admin_view_link,
)
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.export import to_streaming_response


class CompanyMembersInline(MembersInline):
    model = models.Company.members.through
    readonly_fields = MembersInline.readonly_fields


class JobsInline(ItouTabularInline):
    model = models.Company.jobs.through
    extra = 1
    fields = (
        "jobdescription_id_link",
        "appellation",
        "custom_name",
        "created_at",
        "contract_type",
    )
    raw_id_fields = ("appellation", "company", "location")
    readonly_fields = (
        "appellation",
        "custom_name",
        "contract_type",
        "created_at",
        "updated_at",
        "jobdescription_id_link",
    )

    @admin.display(description="lien vers la fiche de poste")
    def jobdescription_id_link(self, obj):
        return get_admin_view_link(obj, content=format_html("<strong>Fiche de poste ID: {}</strong>", obj.id))


class FinancialAnnexesInline(ReadonlyMixin, ItouTabularInline):
    model = models.SiaeFinancialAnnex
    fields = ("number", "is_active", "state", "start_at", "end_at", "created_at")
    readonly_fields = ("number", "is_active", "state", "start_at", "end_at", "created_at")

    ordering = (
        "-end_at",
        "-start_at",
        "-number",
    )

    @admin.display(boolean=True, description="active")
    def is_active(self, obj):
        return obj.is_active


class CompaniesInline(ReadonlyMixin, ItouTabularInline):
    model = models.Company
    fields = ("company_id_link", "kind", "siret", "source", "name", "brand")
    readonly_fields = ("company_id_link", "kind", "siret", "source", "name", "brand")

    def company_id_link(self, obj):
        return get_admin_view_link(obj)


def _companies_serializer(queryset):
    tz = timezone.get_current_timezone()
    return [
        (
            company.siret,
            company.name,
            company.address_on_one_line,
            company.created_by.last_name if company.created_by else "",
            company.created_by.first_name if company.created_by else "",
            company.created_by.phone if company.created_by else "",
            company.created_by.email if company.created_by else "",
            company.created_at.astimezone(tz).strftime("%Y/%m/%d %H:%M"),
        )
        for company in queryset
    ]


@admin.register(models.Company)
class CompanyAdmin(ItouGISMixin, CreatedOrUpdatedByMixin, OrganizationAdmin):
    @admin.action(description="Exporter les entreprises selectionnées")
    def export(self, request, queryset):
        export_qs = queryset.select_related("created_by")
        headers = [
            "SIRET",
            "Nom",
            "Adresse complète",
            "Nom",
            "Prénom",
            "Téléphone",
            "Adresse e-mail",
            "Date de création",
        ]

        return to_streaming_response(
            export_qs,
            "entreprises",
            headers,
            _companies_serializer,
            with_time=True,
        )

    change_form_template = "admin/companies/change_company_form.html"
    list_display = ("pk", "siret", "kind", "name", "department", "geocoding_score", "member_count", "created_at")
    list_filter = (HasMembersFilter, "kind", "block_job_applications", "source", "department")
    raw_id_fields = ("created_by", "convention")
    fieldsets = (
        (
            "Entreprise",
            {
                "fields": (
                    "pk",
                    "siret",
                    "naf",
                    "kind",
                    "name",
                    "brand",
                    "phone",
                    "email",
                    "auth_email",
                    "website",
                    "description",
                    "provided_support",
                    "source",
                    "convention",
                    "is_searchable",
                    "block_job_applications",
                    "job_applications_blocked_at",
                    "spontaneous_applications_open_since",
                    "approvals_list",
                    "rdv_solidarites_id",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                    "fields_history_formatted",
                ),
            },
        ),
        (
            "Adresse",
            {
                "fields": (
                    "address_line_1",
                    "address_line_2",
                    "post_code",
                    "city",
                    "department",
                    "automatic_geocoding_update",
                    "coords",
                    "geocoding_score",
                )
            },
        ),
    )
    search_fields = ("pk", "siret", "name", "city", "department", "post_code", "address_line_1")
    inlines = (CompanyMembersInline, JobsInline, PkSupportRemarkInline)
    actions = [export]

    def get_export_filename(self, request, queryset, file_format):
        return f"Entreprises-{timezone.now():%Y-%m-%d}.{file_format.get_extension()}"

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = [
            "pk",
            "source",
            "created_by",
            "created_at",
            "updated_at",
            "job_applications_blocked_at",
            "geocoding_score",
            "approvals_list",
            "fields_history_formatted",
        ]
        if obj:
            readonly_fields.append("kind")
            if obj.source == models.Company.SOURCE_ASP:
                readonly_fields.extend(["siret", "convention", "auth_email"])
        return readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.source = models.Company.SOURCE_STAFF_CREATED
            if not obj.geocoding_score and obj.geocoding_address:
                try:
                    # Set geocoding.
                    obj.geocode_address()
                except GeocodingDataError:
                    # do nothing, the user has not made any changes to the address
                    pass

        if change and form.cleaned_data.get("automatic_geocoding_update") and obj.geocoding_address:
            try:
                # Refresh geocoding.
                obj.geocode_address()
            except GeocodingDataError:
                messages.error(request, "L'adresse semble erronée car le geocoding n'a pas pu être recalculé.")

        # Pulled-up the save action:
        # many-to-many relationships / cross-tables references
        # have to be saved before using them
        super().save_model(request, obj, form, change)

        if obj.members.count() == 0 and not obj.auth_email:
            messages.warning(
                request,
                (
                    "Cette structure sans membre n'ayant pas d'email "
                    "d'authentification il est impossible de s'y inscrire."
                ),
            )

    def has_delete_permission(self, request, obj=None):
        if obj and obj.siret == enums.POLE_EMPLOI_SIRET:
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        # we specifically target Pole Emploi and not a "RESERVED" kind nor the "ADMIN_CREATED" source.
        # The reason behind this is that at the time of writing, what we want to avoid is to modify
        # Pole Emploi in the admin; we can't make assumptions about the future ADMIN_CREATED or
        # RESERVED Companies that might be created someday.
        if obj and obj.siret == enums.POLE_EMPLOI_SIRET:
            return False
        return super().has_change_permission(request, obj)

    @admin.display(description="Liste des PASS IAE pour cette entreprise")
    def approvals_list(self, obj):
        if obj.pk is None:
            return self.get_empty_value_display()
        url = reverse("admin:approvals_approval_changelist", query={"assigned_company": obj.id, "o": -6})
        count = Approval.objects.is_assigned_to(obj.id).count()
        valid_count = Approval.objects.is_assigned_to(obj.id).valid().count()
        return format_html('<a href="{}">Liste des {} Pass IAE (dont {} valides)</a>', url, count, valid_count)

    @admin.display(description="historique des champs modifiés sur le modèle")
    def fields_history_formatted(self, obj):
        return format_html("<pre><code>{}</code></pre>", pformat(obj.fields_history, width=120))

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "transfer/<int:from_company_pk>",
                self.admin_site.admin_view(self.transfer_view),
                name="transfer_company_data",
            ),
            path(
                "transfer/<int:from_company_pk>/<int:to_company_pk>",
                self.admin_site.admin_view(self.transfer_view),
                name="transfer_company_data",
            ),
        ] + urls

    def transfer_view(self, request, from_company_pk, to_company_pk=None):
        if not self.has_change_permission(request):
            raise PermissionDenied

        from_company = get_object_or_404(models.Company.objects, pk=from_company_pk)
        to_company = get_object_or_404(models.Company, pk=to_company_pk) if to_company_pk is not None else None

        transfer_data = {}
        for transfer_field in transfer.TransferField:
            spec = transfer.TRANSFER_SPECS[transfer_field]
            if model_field := spec.get("model_field"):
                from_data = [getattr(from_company, model_field.name)]
            else:
                from_data = transfer.get_transfer_queryset(from_company, to_company, spec)
            transfer_data[transfer_field] = {
                "data": from_data,
            }

        if not to_company:
            form = SelectTargetCompanyForm(
                from_company=from_company,
                admin_site=self.admin_site,
                data=request.POST or None,
            )
            if request.POST and form.is_valid():
                return redirect(
                    reverse(
                        "admin:transfer_company_data",
                        kwargs={
                            "from_company_pk": from_company.pk,
                            "to_company_pk": form.cleaned_data["to_company"].pk,
                        },
                    )
                )
        else:
            fields_choices = []
            for transfer_field in transfer.TransferField:
                spec = transfer.TRANSFER_SPECS[transfer_field]
                if model_field := spec.get("model_field"):
                    if transfer_data[transfer_field]["data"] == [getattr(to_company, model_field.name)]:
                        transfer_data[transfer_field]["data"] = None
                    else:
                        fields_choices.append((transfer_field.value, transfer_field.label))
                elif from_data := transfer_data[transfer_field]["data"]:
                    s = "s" if len(from_data) > 1 else ""
                    fields_choices.append(
                        (
                            transfer_field.value,
                            f"{transfer_field.label} ({len(from_data)} objet{s} à transférer)",
                        )
                    )

            siae_evaluations = EvaluatedSiae.objects.filter(siae=from_company).exists()
            form = CompanyChooseFieldsToTransfer(
                fields_choices=sorted(fields_choices, key=lambda field: field[1]),
                siae_evaluations=siae_evaluations,
                data=request.POST or None,
            )
            if request.POST and form.is_valid():
                if siae_evaluations and not form.cleaned_data["ignore_siae_evaluations"]:
                    messages.error(
                        request,
                        (
                            f"Impossible de transférer les objets de l'entreprise ID={from_company.pk}: "
                            "il y a un contrôle a posteriori lié. Vérifiez avec l'équipe support."
                        ),
                    )
                else:
                    try:
                        reporter = transfer.transfer_company_data(
                            from_company,
                            to_company,
                            form.cleaned_data["fields_to_transfer"],
                            disable_from_company=form.cleaned_data["disable_from_company"],
                            ignore_siae_evaluations=form.cleaned_data.get("ignore_siae_evaluations", False),
                        )
                    except transfer.TransferError as e:
                        messages.error(request, e.args[0])
                    else:
                        summary_lines = [
                            "-" * 20,
                            f"Transfert du {timezone.now():%Y-%m-%d %H:%M:%S} effectué par {request.user} ",
                            f"de l'entreprise {from_company.pk} vers {to_company.pk}:",
                        ]
                        for report_field, items in reporter.changes.items():
                            if items:
                                summary_lines.extend([f"- {report_field.label}:"] + [f"  * {item}" for item in items])
                        summary_lines += ["-" * 20]
                        summary_text = "\n".join(summary_lines)
                        add_support_remark_to_obj(from_company, summary_text)
                        add_support_remark_to_obj(to_company, summary_text)
                        message = format_html(
                            "Transfert effectué avec succès de l’entreprise {from_company} vers {to_company}.",
                            from_company=from_company,
                            to_company=to_company,
                        )
                        messages.info(request, message)

                        return redirect(
                            reverse(
                                "admin:companies_company_change",
                                kwargs={"object_id": from_company.pk},
                            )
                        )
        title = f"Transfert des données de '{from_company}' [{from_company.kind}]"
        if to_company:
            title += f" vers '{to_company}' [{to_company.kind}]"
        context = self.admin_site.each_context(request) | {
            "media": self.media,
            "opts": self.opts,
            "form": form,
            "from_company": from_company,
            "to_company": to_company,
            "transfer_data": transfer_data,
            "title": title,
            "subtitle": None,
            "has_view_permission": self.has_view_permission(request),
        }

        return TemplateResponse(
            request,
            "admin/companies/transfer_company.html",
            context,
        )


@admin.register(models.JobDescription)
class JobDescriptionAdmin(ItouModelAdmin):
    list_display = (
        "display_name",
        "company",
        "contract_type",
        "created_at",
        "updated_at",
        "is_active",
        "last_employer_update_at",
        "open_positions",
    )
    raw_id_fields = ("appellation", "company", "location")
    list_filter = ("source_kind",)
    search_fields = (
        "pk",
        "company__siret",
        "company__name",
        "custom_name",
        "appellation__name",
    )
    readonly_fields = (
        "pk",
        "source_id",
        "source_kind",
        "source_url",
        "last_employer_update_at",
        "field_history",
    )

    @admin.display(description="Intitulé du poste")
    def display_name(self, obj):
        return obj.custom_name if obj.custom_name else obj.appellation


@admin.register(models.SiaeConvention)
class SiaeConventionAdmin(ItouModelAdmin):
    list_display = ("kind", "siret_signature", "is_active")
    list_filter = ("kind", "is_active")
    raw_id_fields = ("reactivated_by",)
    readonly_fields = (
        "asp_id",
        "kind",
        "siret_signature",
        "deactivated_at",
        "grace_period_end_at",
        "reactivated_by",
        "reactivated_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "kind",
                    "siret_signature",
                    "asp_id",
                )
            },
        ),
        (
            "Statut",
            {
                "fields": (
                    "is_active",
                    "deactivated_at",
                    "grace_period_end_at",
                    "reactivated_by",
                    "reactivated_at",
                )
            },
        ),
        (
            "Autres",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    search_fields = ("pk", "siret_signature", "asp_id")
    inlines = (FinancialAnnexesInline, CompaniesInline, PkSupportRemarkInline)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            old_obj = self.model.objects.get(id=obj.id)
            if obj.is_active and not old_obj.is_active:
                # Itou staff manually reactivated convention.
                obj.reactivated_by = request.user
                obj.reactivated_at = timezone.now()
            if not obj.is_active and old_obj.is_active:
                # Itou staff manually deactivated convention.
                # Start grace period.
                obj.deactivated_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.display(description="fin de délai de grâce")
    def grace_period_end_at(self, obj):
        if not obj.deactivated_at:
            return self.get_empty_value_display()
        return display_for_value(
            obj.deactivated_at + timezone.timedelta(days=models.SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS),
            empty_value_display=self.get_empty_value_display(),
        )


@admin.register(models.SiaeFinancialAnnex)
class SiaeFinancialAnnexAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ("number", "state", "start_at", "end_at")
    list_filter = ("state",)
    raw_id_fields = ("convention",)
    readonly_fields = (
        "number",
        "state",
        "start_at",
        "end_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "number",
                    "convention",
                )
            },
        ),
        (
            "Statut",
            {
                "fields": (
                    "state",
                    "start_at",
                    "end_at",
                )
            },
        ),
        (
            "Autres",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    search_fields = ("pk", "number")
