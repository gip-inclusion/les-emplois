import logging

from django.db.models import DateField
from django.db.models.functions import Cast
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.throttling import UserRateThrottle

from itou.api import AUTH_TOKEN_EXPLANATION_TEXT
from itou.api.employee_record_api.perms import EmployeeRecordAPIPermission
from itou.api.employee_record_api.serializers import (
    EmployeeRecordAPISerializer,
    EmployeeRecordUpdateNotificationAPISerializer,
)
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification, Status
from itou.utils.auth import LoginNotRequiredMixin


logger = logging.getLogger("api_drf")


class EmployeeRecordRateThrottle(UserRateThrottle):
    # For the record, we suspect API calls made by GTA software (used by SIAEs)
    # to be a bit excessive for the least.
    rate = "60/min"


class AbstractEmployeeRecordViewSet(LoginNotRequiredMixin, viewsets.ReadOnlyModelViewSet):
    throttle_classes = [EmployeeRecordRateThrottle]

    # Possible authentication frameworks:
    # - token auth: for external access / real world use case
    # - session auth: for dev context and browsable API
    authentication_classes = [TokenAuthentication, SessionAuthentication]

    # Additional / custom permission classes:
    # Enforce the default one (IsAuthenticated)
    permission_classes = [EmployeeRecordAPIPermission]

    queryset = EmployeeRecord.objects.full_fetch()


def _annotate_convert_created_at(queryset):
    # Add a new `creation_date` field (cast of `created_at` to a date)
    return queryset.annotate(creation_date=Cast("created_at", output_field=DateField()))


class EmployeeRecordViewSet(AbstractEmployeeRecordViewSet):
    # If no queryset class parameter is given (f.i. overriding)
    # a `basename` parameter must be set on the router (see local `urls.py` file)
    # See: https://www.django-rest-framework.org/api-guide/routers/

    serializer_class = EmployeeRecordAPISerializer

    def _filter_by_query_params(self, request, queryset):
        """
        Register query parameters for result filtering
        """
        result = queryset
        params = request.query_params

        # Query params are chainable

        # if no status given, return employee records in PROCESSED state
        if status := params.getlist("status", [Status.PROCESSED]):
            status_filter = [s.upper() for s in status]
            result = result.filter(status__in=status_filter)

        if created := params.get("created"):
            result = _annotate_convert_created_at(result).filter(creation_date=created)

        if since := params.get("since"):
            result = _annotate_convert_created_at(result).filter(creation_date__gte=since)

        # => Add as many params as necessary here (PASS IAE number, SIRET, fuzzy name ...)
        return result.order_by("-created_at")

    def get_queryset(self):
        # We only get to this point if permissions are OK
        queryset = super().get_queryset()

        # Get (registered) query parameters filters
        queryset = self._filter_by_query_params(self.request, queryset)

        # Employee record API will return objects related to
        # all SIAE memberships of authenticated user.
        # There's something similar in context processors, but:
        # - ctx processors are called AFTER this
        # - and only when rendering a template

        # Query optimization:
        # if `companies` is not wrapped into a list,
        # the resulting queryset will be reused as a subquery in the main query (below),
        # leading to ghastly performance issues.
        # Using a list gives a 20-50x speed gain on the query.
        companies = list(
            self.request.user.company_set.filter(memberships__is_active=True, memberships__is_admin=True)
            .active_or_in_grace_period()
            .values_list("pk", flat=True)
        )
        return queryset.filter(job_application__to_company__id__in=companies).order_by("-created_at", "-updated_at")


# Doc section is in French for Swagger / OAS auto doc generation
EmployeeRecordViewSet.__doc__ = f"""\
# API fiches salarié

Cette API retourne la liste des fiches salarié saisies par les SIAE :

- dans l'état `PROCESSED` (par défaut)
- pour toutes les embauches / candidatures des SIAE liées au token d'identification
- classées par date de création (plus récent au plus ancien)

Il est également possible d'obtenir le détail d'une fiche salarié par son
identifiant (dans les mêmes conditions d'autorisation que pour la liste complète).

# Permissions

L'utilisation externe de cette API nécessite un token d'autorisation :

{AUTH_TOKEN_EXPLANATION_TEXT}

L'API peut également être utilisée dans un navigateur :

- seulement dans un environnement de développement
- si l'utilisateur connecté est membre d'une ou plusieurs SIAE éligible aux fiches salarié

# Paramètres

Les paramètres suivants sont :
- utilisables en paramètres de requête (query string),
- chainables : il est possible de préciser un ou plusieurs de ces paramètres pour affiner la recherche.

Sans paramètre fourni, la liste de résultats contient les fiches salarié en l'état

- `PROCESSED` (intégrées par l'ASP).

## `status` : par statut des fiches salarié
Ce paramètre est un tableau permettant de filtrer les fiches retournées par leur statut

Les valeurs possibles pour ce paramètre sont :

- `NEW` : nouvelle fiche en cours de saisie,
- `READY` : la fiche est prête à être transmise à l'ASP,
- `SENT` : la fiche a été transmise et est en attente de traitement,
- `PROCESSED` : la fiche a correctement été intégrée par l'ASP,
- `REJECTED` : la fiche est retournée en erreur après transmission.

### Exemples
- ajouter `?status=NEW` à l'URL pour les nouvelles fiches.
- ajouter `?status=NEW&status=READY` pour les nouvelles fiches et celles prêtes pour la transmission.

## `created` : à date de création
Permet de récupérer les fiches salarié créées à la date donnée en paramètre (au format `AAAA-MM-JJ`).

## `since` : depuis une certaine date
Permet de récupérer les fiches salarié créées depuis date donnée en paramètre (au format `AAAA-MM-JJ`).

# Limitations

L’interrogation de cette API est limitée à 60 appels par minute.
"""


class EmployeeRecordUpdateNotificationViewSet(AbstractEmployeeRecordViewSet):
    queryset = EmployeeRecordUpdateNotification.objects.all()
    serializer_class = EmployeeRecordUpdateNotificationAPISerializer


EmployeeRecordUpdateNotificationViewSet.__doc__ = f"""\
L'utilisation externe de cette API nécessite un token d'autorisation :

{AUTH_TOKEN_EXPLANATION_TEXT}
"""
