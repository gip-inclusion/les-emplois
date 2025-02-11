from dateutil.relativedelta import relativedelta
from django.db.models import F, Prefetch, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view, inline_serializer
from rest_framework import fields, generics, mixins

from itou.api.auth import DepartmentTokenAuthentication
from itou.api.job_application_api import schema
from itou.api.job_application_api.perms import JobApplicationSearchAPIPermission
from itou.api.job_application_api.serializers import (
    JobApplicationSearchRequestSerializer,
    JobApplicationSearchResponseSerializer,
)
from itou.api.job_application_api.throttling import JobApplicationSearchThrottle
from itou.companies.models import JobDescription
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog
from itou.users.enums import UserKind
from itou.utils.auth import LoginNotRequiredMixin


job_application_search_view_description = """
# API de recherche de candidatures

Cette API retourne la liste de candidatures correspondant à une recherche selon les 4 critères suivants :

- Numéro de sécurité sociale du candidat
- Nom du candidat
- Prénom du candidat
- Date de naissance du candidat

# Permissions

L’utilisation de cette API nécessite un token d’autorisation spécifique à chaque conseil départemental.

# Limitations

L’interrogation de cette API est limitée à 120 appels par minute et par conseil départemental.

Elle ne retourne que les candidatures dont le dernier changement date de moins de 3 mois.
"""


@extend_schema_view(
    post=extend_schema(
        operation_id="candidatures_recherche",
        parameters=[
            OpenApiParameter("page", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("page_size", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        request=JobApplicationSearchRequestSerializer,
        responses={
            200: JobApplicationSearchResponseSerializer,
            400: inline_serializer(
                name="JobApplicationSearchRequestInvalidResponse",
                fields={
                    "nir": fields.ListField(
                        child=fields.CharField(label="Erreur individuelle"),
                        label="Erreurs liées au NIR",
                        required=False,
                    ),
                    "nom": fields.ListField(
                        child=fields.CharField(label="Erreur individuelle"),
                        label="Erreurs liées au nom",
                        required=False,
                    ),
                    "prenom": fields.ListField(
                        child=fields.CharField(label="Erreur individuelle"),
                        label="Erreurs liées au prénom",
                        required=False,
                    ),
                    "date_naissance": fields.ListField(
                        child=fields.CharField(label="Erreur individuelle"),
                        label="Erreurs liées à la date de naissance",
                        required=False,
                    ),
                },
            ),
        },
        description=job_application_search_view_description,
        examples=[
            schema.job_application_search_request_example,
            schema.job_application_search_response_valid_example,
            schema.job_application_search_response_valid_no_results_example,
            schema.job_application_search_response_invalid_example,
        ],
    )
)
class JobApplicationSearchView(LoginNotRequiredMixin, mixins.ListModelMixin, generics.GenericAPIView):
    authentication_classes = (DepartmentTokenAuthentication,)
    permission_classes = (JobApplicationSearchAPIPermission,)
    serializer_class = JobApplicationSearchResponseSerializer
    throttle_classes = [JobApplicationSearchThrottle]
    queryset = (
        JobApplication.objects.annotate(
            last_modification_at=Coalesce(
                Subquery(
                    JobApplicationTransitionLog.objects.all().order_by("-timestamp").values("timestamp")[:1],
                ),
                F("updated_at"),
            ),
            employer_email=Coalesce(
                Subquery(
                    JobApplicationTransitionLog.objects.filter(user__kind=UserKind.EMPLOYER)
                    .order_by("-timestamp")
                    .values("user__email")[:1],
                ),
                F("to_company__email"),
            ),
        )
        .select_related(
            "job_seeker__jobseeker_profile",
            "to_company",
            "sender",
            "sender_prescriber_organization",
            "sender_company",
        )
        .prefetch_related(
            "job_seeker__approvals__suspension_set",
            Prefetch(
                "selected_jobs",
                queryset=JobDescription.objects.select_related("appellation__rome", "location", "company"),
            ),
            Prefetch(
                "hired_job",
                queryset=JobDescription.objects.select_related("appellation__rome", "location", "company"),
            ),
        )
        .order_by("-last_modification_at")
    )

    def post(self, request, *args, **kwargs):
        self.request_serializer = JobApplicationSearchRequestSerializer(data=request.data)
        self.request_serializer.is_valid(raise_exception=True)
        return self.list(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        validated_data = self.request_serializer.validated_data
        three_months_ago = timezone.now() - relativedelta(months=3)
        return self.queryset.filter(
            job_seeker__jobseeker_profile__nir=validated_data["nir"],
            job_seeker__jobseeker_profile__birthdate=validated_data["date_naissance"],
            job_seeker__last_name__trigram_similar=validated_data["nom"],
            job_seeker__first_name__trigram_similar=validated_data["prenom"],
            last_modification_at__gte=three_months_ago,
        )
