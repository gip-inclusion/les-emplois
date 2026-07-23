import enum
import logging

from data_inclusion.schema.v1.thematiques import Categorie
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import login_not_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import DetailView
from django.views.generic.base import TemplateView
from django.views.generic.edit import FormView
from itoutils.django.decoupage_administratif.admin_division_parsing import get_division_label
from rest_framework import status

from itou.insertion import models as insertion_models
from itou.insertion.division_labels import bulk_load_division_labels
from itou.insertion.enums import MobilizationEventKind
from itou.insertion.opening_hours import format_osm_hours
from itou.insertion.utils import (
    get_missing_orientation_beneficiary_field_labels,
    get_orient_for_job_seeker_context,
)
from itou.job_applications.enums import SenderKind
from itou.users.enums import UserKind
from itou.users.models import User
from itou.users.perms import can_register_mobilization_event
from itou.utils.apis.dora import DoraAPIClient, DoraAPIException
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.perms.utils import can_edit_personal_information, can_view_personal_information
from itou.utils.phone import normalize_phone_number
from itou.utils.readonly import ReadonlyViewMixin
from itou.utils.session import SessionNamespace, SessionNamespaceException
from itou.utils.urls import get_safe_url
from itou.www.insertion_views.forms import (
    OrientationConformityForm,
    OrientationDocumentsForm,
    OrientationReferentForm,
    OrientationSelectJobSeekerForm,
)
from itou.www.utils.wizard import WizardView


logger = logging.getLogger(__name__)


class StructureCardView(LoginNotRequiredMixin, ReadonlyViewMixin, TemplateView):
    template_name = "insertion/structure_card.html"

    def setup(self, request, structure_uid, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.structure = get_object_or_404(
            insertion_models.Structure.objects.select_related("source").prefetch_related(
                Prefetch(
                    "services",
                    queryset=insertion_models.Service.objects.order_by("name")
                    .select_related("kind")
                    .prefetch_related("receptions"),
                ),
            ),
            uid=structure_uid,
        )

    def format_opening_hours(self):
        opening_hours = []

        osm_hours = format_osm_hours(self.structure.opening_hours)

        if not osm_hours:
            return None

        for entry in osm_hours["entries"]:
            label = entry["label"][:3]
            hours = entry["hours"]
            comment = f"({entry['comment']}) " if entry["comment"] else ""

            opening_hours.append(f"{label}: {hours} {comment}")

        formatted_opening_hours = "• ".join(opening_hours).rstrip()

        public_holidays_notice = "(Hors jours fériés)" if osm_hours["has_ph_off"] else ""

        return f"{formatted_opening_hours} {public_holidays_notice}"

    def get_context_data(self, **kwargs):
        services = list(self.structure.services.all())
        for service, perimeter in zip(
            services,
            bulk_load_division_labels([service.eligibility_zones for service in services]),
        ):
            service.perimeter = perimeter or "France entière"
        return super().get_context_data(**kwargs) | {
            "structure": self.structure,
            "matomo_custom_title": "Fiche structure d’insertion",
            "back_url": get_safe_url(
                self.request,
                "back_url",
                fallback_url=reverse("search:services_home"),
            ),
            "services": services,
            "formatted_opening_hours": self.format_opening_hours(),
            "can_register_mobilization_event": can_register_mobilization_event(self.request),
        }


class ServiceDetailView(LoginNotRequiredMixin, DetailView):
    model = insertion_models.Service
    queryset = insertion_models.Service.objects.select_related(
        "source",
        "fee",
        "kind",
        "structure",
        "structure__source",
        "insee_city",
    ).prefetch_related(
        "thematics",
        "publics",
        Prefetch("receptions", queryset=insertion_models.GenericReferenceItem.objects.order_by("label")),
        "mobilizations",
        "mobilization_publics",
        "mobilization_modes_beneficiaries",
        "mobilization_modes_professionals",
    )
    slug_field = "uid"
    slug_url_kwarg = "service_uid"
    template_name = "insertion/service_card.html"
    context_object_name = "service"

    def format_categories(self) -> list[tuple[str, str]]:
        formatted_categories = []
        for thematic in self.object.thematics.all():
            category = thematic.value.split("--")[0]
            category_label = Categorie(category).label
            subcategory_label = thematic.label
            formatted_categories.append((category_label, subcategory_label))
        return formatted_categories

    def get_context_data(self, **kwargs):
        has_contact_to_display = (
            self.object.contact_full_name or self.object.contact_email or self.object.contact_phone
        )
        user_is_authorized = (
            self.object.contact_is_public or self.request.user.is_authenticated and not self.request.user.is_job_seeker
        )
        can_view_modal = has_contact_to_display and user_is_authorized
        return (
            super().get_context_data(**kwargs)
            | get_orient_for_job_seeker_context(self.request)
            | {
                "formatted_opening_hours": format_osm_hours(self.object.opening_hours),
                "back_url": get_safe_url(self.request, "back_url", fallback_url=reverse("search:services_home")),
                "matomo_custom_title": "Fiche de la service d'insértion",
                "geographic_perimeter": get_division_label(self.object.eligibility_zones) or "France entière",
                "credential_documents": self.object.generate_credential_documents_info(),
                "show_mobilization_section": self.object.has_mobilization_modes(),
                "professionals_has_autre": any(
                    m.value == "autre" for m in self.object.mobilization_modes_professionals.all()
                ),
                "beneficiaries_has_autre": any(
                    m.value == "autre" for m in self.object.mobilization_modes_beneficiaries.all()
                ),
                "formatted_categories": self.format_categories(),
                "can_view_modal": can_view_modal,
                "can_register_mobilization_event": can_register_mobilization_event(self.request),
            }
        )


@login_not_required
@require_POST
def register_mobilization_event(request):
    if not can_register_mobilization_event(request):
        raise PermissionDenied()

    if not (kind := request.POST.get("kind")) or kind not in MobilizationEventKind.values:
        return JsonResponse({"message": "missing or bad kind"}, status=status.HTTP_400_BAD_REQUEST)
    if service_uid := request.POST.get("service_uid"):
        service = get_object_or_404(insertion_models.Service.objects.select_related("structure"), uid=service_uid)
        structure = service.structure
    elif structure_uid := request.POST.get("structure_uid"):
        service = None
        structure = get_object_or_404(insertion_models.Structure, uid=structure_uid)
    else:
        return JsonResponse({"message": "missing structure_uid"}, status=status.HTTP_400_BAD_REQUEST)

    organization = (
        request.current_organization if request.user.is_authenticated and request.user.is_professional else None
    )

    try:
        insertion_models.MobilizationEvent.objects.create_mobilization_event(
            session_key=request.session.session_key,
            kind=kind,
            user=request.user,
            organization=organization,
            structure=structure,
            service=service,
            service_external_link=request.POST.get("service_external_link", ""),
        )
    except Exception:
        logger.warning(
            "Unable to register mobilization event for user=%s, structure=%s, service=%s, kind=%s",
            request.user.pk,
            structure.uid,
            service.uid if service else None,
            kind,
        )
        return JsonResponse({"message": "server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return JsonResponse({"message": "ok"})


class OrientationStep(enum.StrEnum):
    CONFORMITY = "confirm"
    REFERENT = "fill"
    DOCUMENTS = "submit"
    do_not_call_in_templates = enum.nonmember(True)


def start_orientation(request, service_uid):
    service = get_object_or_404(insertion_models.Service, uid=service_uid, is_orientable_with_form=True)
    if not (job_seeker_public_id := request.GET.get("job_seeker_public_id")):
        logger.info(
            "orientation wizard start_without_job_seeker user=%s service_uid=%s",
            request.user.pk,
            service.uid,
        )
        return HttpResponseRedirect(
            reverse(
                "insertion_views:orientation_select_job_seeker",
                kwargs={"service_uid": service.uid},
            )
        )
    job_seeker = get_object_or_404(User, public_id=job_seeker_public_id, kind=UserKind.JOB_SEEKER)
    logger.info(
        "orientation wizard start user=%s service_uid=%s job_seeker=%s",
        request.user.pk,
        service.uid,
        job_seeker.public_id,
    )
    return OrientationWizardView.initialize_session_and_start(
        request,
        reset_url=reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid}),
        extra_session_data={
            "service_uid": service.uid,
            "job_seeker_public_id": str(job_seeker.public_id),
        },
    )


class OrientationSelectJobSeekerView(FormView):
    form_class = OrientationSelectJobSeekerForm
    template_name = "insertion/orientation_select_job_seeker.html"

    def dispatch(self, request, *args, **kwargs):
        if not (request.from_employer or request.from_prescriber):
            raise PermissionDenied("Vous n'êtes pas autorisé à orienter un usager.")
        return super().dispatch(request, *args, **kwargs)

    def setup(self, request, *args, service_uid, **kwargs):
        super().setup(request, *args, **kwargs)
        self.service = get_object_or_404(
            insertion_models.Service.objects.select_related("kind", "structure"),
            uid=service_uid,
            is_orientable_with_form=True,
        )

    def get_form_kwargs(self):
        return super().get_form_kwargs() | {"request": self.request}

    def form_valid(self, form):
        return HttpResponseRedirect(
            reverse(
                "insertion_views:start_orientation",
                kwargs={"service_uid": self.service.uid},
                query={"job_seeker_public_id": form.cleaned_data["job_seeker"]},
            )
        )

    def get_context_data(self, **kwargs):
        service_detail_url = reverse("insertion_views:service_detail", kwargs={"service_uid": self.service.uid})
        return super().get_context_data(**kwargs) | {
            "service": self.service,
            "reset_url": service_detail_url,
            "create_job_seeker_url": reverse(
                "job_seekers_views:get_or_create_start",
                query={
                    "tunnel": "orientation",
                    "from_url": service_detail_url,
                    "service_uid": self.service.uid,
                },
            ),
            "matomo_custom_title": "Orientation service - rechercher un usager",
        }


class OrientationResultBaseView(TemplateView):
    matomo_custom_title = None

    def get_context_data(self, **kwargs):
        service = get_object_or_404(
            insertion_models.Service.objects.select_related("kind", "structure"),
            uid=self.kwargs["service_uid"],
        )
        job_seeker = get_object_or_404(
            User.objects.select_related("jobseeker_profile"),
            public_id=self.request.GET.get("job_seeker_public_id"),
            kind=UserKind.JOB_SEEKER,
        )
        return super().get_context_data(**kwargs) | {
            "service": service,
            "job_seeker": job_seeker,
            "can_view_personal_information": can_view_personal_information(self.request, job_seeker),
            "matomo_custom_title": self.matomo_custom_title,
        }


class OrientationConfirmationView(OrientationResultBaseView):
    template_name = "insertion/orientation_confirmation.html"
    matomo_custom_title = "Demande d'orientation transmise"


class OrientationWizardView(WizardView):
    url_name = "insertion_views:orientation_steps"
    expected_session_kind = "orientation"
    template_name = "insertion/orientation_wizard.html"
    steps_config = {
        OrientationStep.CONFORMITY: OrientationConformityForm,
        OrientationStep.REFERENT: OrientationReferentForm,
        OrientationStep.DOCUMENTS: OrientationDocumentsForm,
    }

    def setup_wizard(self):
        self.dora_client = DoraAPIClient(settings.DORA_API_BASE_URL, settings.DORA_API_TOKEN)
        self.service = get_object_or_404(
            insertion_models.Service.objects.select_related("kind", "structure", "fee", "source").prefetch_related(
                "publics",
            ),
            uid=self.wizard_session.get("service_uid"),
        )
        self.job_seeker = get_object_or_404(
            User.objects.select_related("jobseeker_profile"),
            public_id=self.wizard_session.get("job_seeker_public_id"),
            kind=UserKind.JOB_SEEKER,
        )

    def get_form(self, step, data):
        files = self.request.FILES if self.request.method == "POST" else None
        return self.get_form_class(step)(
            initial=self.get_form_initial(step), data=data, files=files, **self.get_form_kwargs(step)
        )

    def get_form_kwargs(self, step):
        if step == OrientationStep.CONFORMITY:
            return {"job_seeker": self.job_seeker}
        return {}

    def get_form_initial(self, step):
        if step == OrientationStep.REFERENT and self.wizard_session.get(step) is self.wizard_session.NOT_SET:
            user = self.request.user
            return {
                "referent_last_name": user.last_name,
                "referent_first_name": user.first_name,
                "referent_phone": user.phone,
                "referent_email": user.email,
            }
        return super().get_form_initial(step)

    def get(self, request, *args, **kwargs):
        logger.info(
            "orientation wizard step_viewed step=%s user=%s service_uid=%s job_seeker=%s",
            self.step,
            request.user.pk,
            self.service.uid,
            self.job_seeker.public_id,
        )
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.step == OrientationStep.DOCUMENTS:
            if invalid_step := self.find_step_with_invalid_data_until_step(self.step):
                return HttpResponseRedirect(self.get_step_url(invalid_step))

            if not self.form.is_valid():
                return self.render_to_response(self.get_context_data(**kwargs))

            cleaned = self.form.cleaned_data
            attachments = []
            for field in ("credentials_documents_files", "credentials_proof_files"):
                for uploaded_file in cleaned.get(field) or []:
                    uploaded_file.seek(0)
                    attachments.append((uploaded_file.name, uploaded_file))

            referent_data = self.wizard_session.get(OrientationStep.REFERENT)
            payload = {
                "di_service_id": self.service.uid,
                "di_service_name": self.service.name,
                "di_service_address_line": self.service.address_on_one_line or "à distance",
                "di_contact_email": self.service.contact_email,
                "di_contact_name": self.service.contact_full_name,
                "di_contact_phone": self.service.contact_phone,
                "di_structure_name": self.service.structure.name,
                "beneficiary_first_name": self.job_seeker.first_name,
                "beneficiary_last_name": self.job_seeker.last_name,
                "beneficiary_email": self.job_seeker.email,
                "beneficiary_phone": normalize_phone_number(self.job_seeker.phone or "") or "",
                "referent_first_name": referent_data["referent_first_name"],
                "referent_last_name": referent_data["referent_last_name"],
                "referent_email": referent_data["referent_email"],
                "referent_phone": referent_data["referent_phone"],
                "data_protection_commitment": cleaned["gdpr_consent"],
            }
            if orientation_reason := referent_data.get("orientation_reason"):
                payload["orientation_reasons"] = orientation_reason
            if pole_emploi_id := self.job_seeker.jobseeker_profile.pole_emploi_id:
                payload["beneficiary_france_travail_number"] = pole_emploi_id
            if (organization := request.current_organization) and (prescriber := request.user):
                emplois_data = {
                    "beneficiary_id": str(self.job_seeker.public_id),
                    "structure_id": str(organization.uid),
                    "structure_name": organization.name,
                    "prescriber_id": str(prescriber.public_id),
                    "prescriber_email": prescriber.email,
                    "prescriber_first_name": prescriber.first_name,
                    "prescriber_last_name": prescriber.last_name,
                }
                if prescriber_phone := normalize_phone_number(prescriber.phone or referent_data["referent_phone"]):
                    emplois_data["prescriber_phone"] = prescriber_phone
                if organization.siret:
                    emplois_data["structure_siret"] = organization.siret
                payload["emplois_data"] = emplois_data

            try:
                orientation_response = self.dora_client.create_orientation(payload, attachments)
            except DoraAPIException:
                logger.info(
                    "orientation wizard submission_failed reason=create_orientation "
                    "user=%s service_uid=%s job_seeker=%s",
                    request.user.pk,
                    self.service.uid,
                    self.job_seeker.public_id,
                )
                messages.error(
                    request,
                    "Votre demande n'a pas été transmise suite à un problème technique. Merci de réessayer.",
                )
                return self.render_to_response(self.get_context_data(**kwargs))

            logger.info(
                "orientation wizard submitted user=%s service_uid=%s job_seeker=%s",
                request.user.pk,
                self.service.uid,
                self.job_seeker.public_id,
            )

            if request.from_employer:
                sender_kind = SenderKind.EMPLOYER
                sender_prescriber_organization = None
                sender_company = request.current_organization
            else:
                sender_kind = SenderKind.PRESCRIBER
                sender_prescriber_organization = request.current_organization
                sender_company = None

            orientation = insertion_models.Orientation.from_data(
                service=self.service,
                beneficiary=self.job_seeker,
                sender=request.user,
                id=orientation_response["emplois_sync_uid"],
                sender_kind=sender_kind,
                sender_prescriber_organization=sender_prescriber_organization,
                sender_company=sender_company,
                referent_last_name=referent_data["referent_last_name"],
                referent_first_name=referent_data["referent_first_name"],
                referent_phone=referent_data["referent_phone"],
                referent_email=referent_data["referent_email"],
                orientation_reasons=referent_data.get("orientation_reason") or "",
                data_protection_commitment=cleaned["gdpr_consent"],
                attachments=orientation_response.get("beneficiary_attachments") or [],
            )
            # force_insert: the primary key (emplois_sync_uid) is set by hand, so save() would
            # otherwise issue a redundant UPDATE probe before the INSERT.
            orientation.save(force_insert=True)
            self.link_mobilization_event(orientation)

            confirmation_url = reverse(
                "insertion_views:orientation_confirmation",
                kwargs={"service_uid": self.service.uid},
                query={"job_seeker_public_id": self.job_seeker.public_id},
            )
            self.wizard_session.delete()
            return HttpResponseRedirect(confirmation_url)

        if self.form.is_valid():
            logger.info(
                "orientation wizard step_completed step=%s user=%s service_uid=%s job_seeker=%s",
                self.step,
                request.user.pk,
                self.service.uid,
                self.job_seeker.public_id,
            )
        return super().post(request, *args, **kwargs)

    def link_mobilization_event(self, orientation):
        request = self.request
        try:
            event = (
                insertion_models.MobilizationEvent.objects.filter(
                    kind=MobilizationEventKind.SERVICE_ORIENTATION,
                    session_key=request.session.session_key,
                    service=self.service,
                    user=request.user,
                    orientation__isnull=True,
                )
                .order_by("-created_at")
                .first()
            )
            if event is not None:
                insertion_models.MobilizationEvent.objects.filter(pk=event.pk).update(orientation=orientation)
        except Exception:
            logger.exception(
                "orientation wizard mobilization_link_failed emplois_sync_uid=%s user=%s service_uid=%s",
                orientation.pk,
                request.user.pk,
                self.service.uid,
            )

    def get_context_data(self, **kwargs):
        matomo_titles = {
            OrientationStep.CONFORMITY: "Orientation service - valider conformité",
            OrientationStep.REFERENT: "Orientation service - compléter demande",
            OrientationStep.DOCUMENTS: "Orientation service - documents justificatifs",
        }
        return super().get_context_data(**kwargs) | {
            "service": self.service,
            "job_seeker": self.job_seeker,
            "can_view_personal_information": can_view_personal_information(self.request, self.job_seeker),
            "can_edit_personal_information": can_edit_personal_information(self.request, self.job_seeker),
            "missing_beneficiary_fields": get_missing_orientation_beneficiary_field_labels(self.job_seeker),
            "credential_documents": self.service.generate_credential_documents_info(),
            "OrientationStep": OrientationStep,
            "matomo_custom_title": matomo_titles[self.step],
            "matomo_custom_url": f"orientations/<uuid:session_uuid>/create/{self.step}/",
            "matomo_event_name": f"orientation-{self.step}-submit",
            "show_orientation_disclaimer": not self.wizard_session.get("disclaimer_dismissed", False),
            "orientation_session_uuid": self.wizard_session.name,
            "exit_url": get_orient_for_job_seeker_context(self.request)["exit_url"],
        }


@require_POST
def dismiss_orientation_disclaimer(request, session_uuid):
    try:
        wizard_session = SessionNamespace(
            request.session,
            OrientationWizardView.expected_session_kind,
            session_uuid,
        )
    except SessionNamespaceException:
        raise Http404
    wizard_session.set("disclaimer_dismissed", True)
    return HttpResponseRedirect(
        get_safe_url(
            request,
            "next",
            fallback_url=reverse(
                OrientationWizardView.url_name,
                kwargs={"session_uuid": session_uuid, "step": OrientationStep.CONFORMITY},
            ),
        )
    )
