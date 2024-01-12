from rest_framework import authentication, generics

from itou.api import AUTH_TOKEN_EXPLANATION_TEXT
from itou.users.enums import UserKind
from itou.users.models import User

from .perms import ApplicantsAPIPermission
from .serializers import ApplicantSerializer


class ApplicantsView(generics.ListAPIView):
    authentication_classes = (
        authentication.TokenAuthentication,
        authentication.SessionAuthentication,
    )
    permission_classes = (ApplicantsAPIPermission,)
    serializer_class = ApplicantSerializer

    def get_queryset(self):
        multi_companies_mode = bool(self.request.query_params.get("mode_multi_structures")) is True
        companies_ids = (
            self.request.user.active_or_in_grace_period_company_memberships()
            .all()
            .values_list("company_id", flat=True)
        )

        if not multi_companies_mode:
            # Legacy behaviour.
            # Return the first membership available.
            companies_ids = companies_ids[:1]

        return (
            User.objects.filter(job_applications__to_company_id__in=companies_ids, kind=UserKind.JOB_SEEKER)
            .select_related("jobseeker_profile__birth_place", "jobseeker_profile__birth_country")
            .prefetch_related("job_applications")
            .order_by("-pk")
        )


ApplicantsView.__doc__ = f"""\
# Liste des candidats par structure

Cette API retourne la liste de tous les demandeurs d'emploi liés aux candidatures reçues par
la ou les structure(s) sélectionnée(s).

Les candidats sont triés par date de création dans la base des emplois de l'inclusion,
du plus récent au plus ancien.

# Permissions

L'utilisation de cette API nécessite un jeton d'autorisation (`token`) :

{AUTH_TOKEN_EXPLANATION_TEXT}

Le compte administrateur utilisé peut être membre d'une ou de plusieurs structures.
Par défaut, l'API renvoie les candidatures reçues par la première structure dont le compte est membre
car la première version avait été pensée ainsi.

# Paramètres

- mode_multi_structures : envoie les candidatures envoyées à toutes les organisations auxquelles
appartient l'utilisateur de l'API.
"""
