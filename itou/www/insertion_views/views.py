import enum

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Prefetch
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import DetailView
from django.views.generic.base import TemplateView

from itou.insertion.models import GenericReferenceItem, Service, Structure
from itou.insertion.opening_hours import format_osm_hours
from itou.insertion.utils import get_orientation_jwt
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.apis.dora import DoraAPIClient, DoraAPIException
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.pagination import pager
from itou.utils.urls import get_safe_url
from itou.www.apply.views.submit_views import ApplyForJobSeekerMixin
from itou.www.insertion_views.forms import (
    OrientationConformityForm,
    OrientationDocumentsForm,
    OrientationReferentForm,
)
from itou.www.utils.wizard import WizardView


class StructureCardView(LoginNotRequiredMixin, ApplyForJobSeekerMixin, TemplateView):
    template_name = "insertion/structure_card.html"

    def setup(self, request, structure_uid, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.structure = get_object_or_404(
            Structure.objects.prefetch_related(
                Prefetch(
                    "services",
                    queryset=Service.objects.order_by("name").select_related("kind"),
                ),
            ),
            uid=structure_uid,
        )

    def get_context_data(self, **kwargs):
        services_page = pager(self.structure.services.all(), self.request.GET.get("page"), items_per_page=5)

        return super().get_context_data(**kwargs) | {
            "structure": self.structure,
            "matomo_custom_title": "Fiche structure d’insertion",
            "back_url": get_safe_url(self.request, "back_url", fallback_url=reverse("home:hp")),
            "active_tab": "services" if self.request.GET.get("page") else "description",
            "services_page": services_page,
        }

    def get_template_names(self):
        if self.request.htmx:
            return ["insertion/includes/structure_card_tab_services.html"]
        return [self.template_name]


class ServiceCardView(LoginNotRequiredMixin, ApplyForJobSeekerMixin, DetailView):
    model = Service
    queryset = Service.objects.select_related(
        "source",
        "fee",
        "kind",
        "structure",
        "structure__source",
        "insee_city",
    ).prefetch_related(
        "thematics",
        "publics",
        models.Prefetch("receptions", queryset=GenericReferenceItem.objects.order_by("label")),
        "mobilizations",
        "mobilization_publics",
    )
    slug_field = "uid"
    slug_url_kwarg = "service_uid"
    template_name = "services/../../templates/insertion/service_card.html"
    context_object_name = "service"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["formatted_opening_hours"] = format_osm_hours(self.object.opening_hours)
        context["back_url"] = "#"  # TODO: link to the service list once it exists
        context["matomo_custom_title"] = "Fiche de la service d'insértion"
        context["orientation_jwt"] = get_orientation_jwt(self.request)
        return context


class OrientationStep(enum.StrEnum):
    CONFORMITY = "valider-conformite"
    REFERENT = "completer-demande"
    DOCUMENTS = "documents-justificatifs"
    do_not_call_in_templates = enum.nonmember(True)


@login_required
@require_POST
def safe_upload_proxy(request: HttpRequest) -> JsonResponse:
    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"error": "Aucun fichier fourni."}, status=400)
    try:
        with DoraAPIClient(settings.DORA_API_BASE_URL, settings.DORA_API_TOKEN) as client:
            client.safe_upload(f.name, f)
    except DoraAPIException:
        return JsonResponse(
            {"error": f"Une erreur est survenue lors du transfert du fichier « {f.name} »."},
            status=502,
        )
    return JsonResponse({"name": f.name})


@login_required
def start_orientation(request: HttpRequest, service_uid: str) -> HttpResponse:
    service = get_object_or_404(Service, uid=service_uid)
    if not service.is_orientable_with_form:
        raise Http404

    job_seeker_public_id = request.GET.get("job_seeker_public_id")
    job_seeker = get_object_or_404(User, public_id=job_seeker_public_id, kind=UserKind.JOB_SEEKER)

    return OrientationWizardView.initialize_session_and_start(
        request,
        reset_url=request.META.get("HTTP_REFERER") or "/",
        extra_session_data={
            "config": {
                "service_uid": service_uid,
                "job_seeker_pk": str(job_seeker.pk),
            }
        },
    )


class OrientationWizardView(LoginRequiredMixin, WizardView):
    url_name = "insertion_views:orientation_steps"
    expected_session_kind = "service-orientation"
    steps_config = {
        OrientationStep.CONFORMITY: OrientationConformityForm,
        OrientationStep.REFERENT: OrientationReferentForm,
        OrientationStep.DOCUMENTS: OrientationDocumentsForm,
    }
    template_name = "insertion/orientation_wizard.html"

    def load_session(self, session_uuid: str) -> None:
        super().load_session(session_uuid)
        config = self.wizard_session.get("config", {})
        self.service_uid = config.get("service_uid")
        self.job_seeker_pk = config.get("job_seeker_pk")

    def setup_wizard(self) -> None:
        super().setup_wizard()
        self.service = get_object_or_404(Service, uid=self.service_uid)
        self.job_seeker = get_object_or_404(User, pk=self.job_seeker_pk, kind=UserKind.JOB_SEEKER)

    def get_form_initial(self, step: str) -> dict:
        initial = super().get_form_initial(step)
        if step == OrientationStep.REFERENT and not initial:
            user = self.request.user
            initial = {
                "referent_last_name": user.last_name,
                "referent_first_name": user.first_name,
                "referent_phone": user.phone,
                "referent_email": user.email,
            }
        return initial

    def get_context_data(self, **kwargs: object) -> dict:
        return super().get_context_data(**kwargs) | {
            "service": self.service,
            "job_seeker": self.job_seeker,
            "OrientationStep": OrientationStep,
        }

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if self.step == OrientationStep.DOCUMENTS:
            self.form = self.get_form_class(self.step)(
                data=request.POST,
                files=request.FILES,
                initial=self.get_form_initial(self.step),
            )
            if self.form.is_valid():
                cleaned = self.form.cleaned_data
                stored_data = {"gdpr_consent": cleaned["gdpr_consent"]}
                for field_name in ("credentials_documents_files", "credentials_proof_files"):
                    files = cleaned.get(field_name) or []
                    stored_data[field_name] = [
                        default_storage.save(f"temporary_storage/orientation/{f.name}", f) for f in files
                    ]
                self.wizard_session.set(self.step, stored_data)
                if self.next_step:
                    return HttpResponseRedirect(self.get_step_url(self.next_step))
                else:
                    if invalid_step := self.find_step_with_invalid_data_until_step(self.step):
                        messages.warning(request, "Certaines informations sont absentes ou invalides")
                        return HttpResponseRedirect(self.get_step_url(invalid_step))
                    success_url = self.done()
                    self.wizard_session.delete()
                    return HttpResponseRedirect(success_url)
            context = self.get_context_data(**kwargs)
            return self.render_to_response(context)
        return super().post(request, *args, **kwargs)

    def done(self) -> str:
        # TODO: implement submission (send emails, create DB record)
        return self.reset_url
