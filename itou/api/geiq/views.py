from django.contrib.auth.models import AnonymousUser
from django.db.models import Prefetch
from django.db.models.functions import Substr
from django.forms import ValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import authentication, exceptions, generics, permissions, status

from itou.api.models import CompanyApiToken
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.job_applications.enums import Prequalification, ProfessionalSituationExperience
from itou.job_applications.models import JobApplication, JobApplicationWorkflow, PriorAction
from itou.utils.validators import validate_siren

from .serializers import GeiqJobApplicationSerializer


class GeiqApiAnonymousUser(AnonymousUser):
    pass


class GeiqApiAuthentication(authentication.TokenAuthentication):
    model = CompanyApiToken

    def authenticate_credentials(self, key):
        try:
            api_token = self.model.objects.prefetch_related("companies").get(key=key)
            return (GeiqApiAnonymousUser(), api_token)
        except (ValidationError, self.model.DoesNotExist):
            raise exceptions.AuthenticationFailed("Invalid token.")


class IsSessionAdminOrToken(permissions.BasePermission):
    def has_permission(self, request, view):
        if isinstance(request.user, GeiqApiAnonymousUser):
            return True
        return request.user.is_superuser


class InvalidSirenError(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST


class GeiqJobApplicationListView(generics.ListAPIView):
    authentication_classes = (
        GeiqApiAuthentication,
        authentication.SessionAuthentication,
    )
    permission_classes = (IsSessionAdminOrToken,)
    serializer_class = GeiqJobApplicationSerializer

    def get_queryset(self):
        extra_filters = {}
        api_token = self.request.auth
        if api_token:
            geiqs = api_token.companies.all()
            antennas = (
                Company.objects.filter(source=Company.SOURCE_USER_CREATED, kind=CompanyKind.GEIQ)
                .annotate(siren=Substr("siret", pos=1, length=9))
                .filter(siren__in=[geiq.siret[:9] for geiq in geiqs])
            )
            extra_filters.update({"to_company__in": geiqs | antennas})
        siren = self.request.query_params.get("siren")
        if siren is not None:
            try:
                validate_siren(siren)
            except ValidationError:
                raise InvalidSirenError("Invalid SIREN.")
            extra_filters.update({"to_company__siret__startswith": siren[:9]})
        return (
            JobApplication.objects.filter(
                state=JobApplicationWorkflow.STATE_ACCEPTED,
                to_company__kind=CompanyKind.GEIQ,
                **extra_filters,
            )
            .select_related(
                "to_company",
                "sender_prescriber_organization",
                "job_seeker__jobseeker_profile",
                "geiq_eligibility_diagnosis",
                "hired_job__appellation__rome",
            )
            .prefetch_related(
                "geiq_eligibility_diagnosis__administrative_criteria",
                Prefetch(
                    "prior_actions",
                    queryset=PriorAction.objects.filter(action__in=Prequalification.values),
                    to_attr="prequalifications",
                ),
                Prefetch(
                    "prior_actions",
                    queryset=PriorAction.objects.filter(action__in=ProfessionalSituationExperience.values),
                    to_attr="mises_en_situation_pro",
                ),
            )
            .order_by(
                "to_company__siret",
                "job_seeker__last_name",
                "job_seeker__first_name",
                "pk",
            )
        )

    @extend_schema(operation_id="list")
    def get(self, request, *args, **kwargs):
        """
        # Liste des embauches réalisées en GEIQ

        Retourne la liste complète des embauches réalisées en GEIQ connues des Emplois de l'inclusion.
        Ces embauches représentent des candidatures acceptées.

        Elles ne seront plus listées par l'API une fois le contrat terminé.
        """
        return self.list(request, *args, **kwargs)
