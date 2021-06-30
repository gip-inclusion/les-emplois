from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication, TokenAuthentication

from itou.api.employee_record_api.perms import EmployeeRecordAPIPermission
from itou.employee_record.models import EmployeeRecord
from itou.employee_record.serializers import EmployeeRecordSerializer
from itou.siaes.models import SiaeMembership


class EmployeeRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """
    # API fiches salarié

    Cette API retourne la liste des fiches salarié saisies par les SIAE :

    - dans l'état `PROCESSED` (par défaut)
    - pour toutes les embauches / candidatures des SIAE liées au token d'identification
    - classées par date de création et date de mise à jour (plus récent au plus ancien)

    Il est également possible d'obtenir le détail d'une fiche salarié par son
    identifiant (dans les mêmes conditions d'autorisation que pour la liste complète)

    # Permissions

    L'utilisation externe de cette API nécessite l'utilisation d'un token d'autorisation
    (voir le endpoint `auth-token`).

    L'API peut également être utilisée dans un navigateur :

    - seulement dans un environnement de développement
    - si l'utilisateur connecté est membre d'une ou plusieurs SIAE éligible aux fiches salarié

    """

    # Above section is in french for Swagger / OAS auto doc generation

    # If no queryset class parameter is given (f.i. overidding)
    # a `basename` parameter must be set on the router (see local `urls.py` file)
    # See: https://www.django-rest-framework.org/api-guide/routers/

    serializer_class = EmployeeRecordSerializer

    # Possible authentication frameworks:
    # - token auth: for external access / real world use case
    # - session auth: for dev context
    authentication_classes = [TokenAuthentication, SessionAuthentication]

    # Additional / custom permission classes:
    # Enforce the default one (IsAuthenticated)
    permission_classes = [EmployeeRecordAPIPermission]

    def get_queryset(self):
        # We only get to this point if permissions are OK
        queryset = EmployeeRecord.objects.full_fetch().processed()

        # Employee record API will return objects related to
        # all SIAE memberships of authenticated user.
        # There's something similar in context processors, but:
        # - ctx processors are called AFTER this
        # - and only when rendering a template
        memberships = SiaeMembership.objects.filter(user=self.request.user).values("siae")

        return queryset.filter(job_application__to_siae__in=memberships).order_by("-created_at", "-updated_at")
