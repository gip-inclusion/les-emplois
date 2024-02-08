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
        # unique company asserted by permission class
        company_id = self.request.user.companymembership_set.get().company_id

        return (
            User.objects.filter(job_applications__to_company_id=company_id, kind=UserKind.JOB_SEEKER)
            .select_related("jobseeker_profile__birth_place", "jobseeker_profile__birth_country")
            .prefetch_related("job_applications")
            .order_by("-pk")
        )


ApplicantsView.__doc__ = f"""\
# Liste des candidats par structure

Cette API retourne la liste de tous les demandeurs d'emploi liés à une candidature pour la structure en cours.

Les candidats sont triés par date de création dans la base des emplois de l'inclusion,
du plus récent au plus ancien.

# Permissions

L'utilisation de cette API nécessite un jeton d'autorisation (`token`) :

{AUTH_TOKEN_EXPLANATION_TEXT}

Le compte administrateur utilisé ne doit être membre **que** de la structure
dont on souhaite récupérer la liste de candidats, et non membre de plusieurs
structures.

Dans l'idéal, il s'agit d'un compte dédié à l'utilisation de l'API.

# Paramètres

Cette API ne dispose pas de paramètres de filtrage ou de recherche :
    elle retourne l'intégralité des candidats de la structure.
"""
