from rest_framework import authentication, generics

from itou.users.models import User

from .perms import ApplicantsAPIPermission
from .serializers import ApplicantSerializer


class ApplicantsView(generics.ListAPIView):
    """
    # Liste des candidats par structure

    Cette API retourne la liste de tous les demandeurs d'emploi liés à une candidature pour la structure en cours.

    Les candidats sont triés par date de création dans la base des emplois de l'inclusion,
    du plus récent au plus ancien.

    # Permissions

    L'utilisation de cette API nécessite un jeton d'autorisation (`token`).

    Pour l'obtention d'un jeton, veuillez utiliser **les identifiants d'un compte administrateur de la structure.**

    Voir le endpoint `auth-token` pour obtenir un jeton.

    Ce compte ne doit être *uniquement membre* de la structure dont on souhaite récupérer la liste de candidats.

    Dans l'idéal, il s'agit d'un compte dédié à l'utilisation de l'API.


    # Paramètres

    Cette api ne dispose pas de paramètres de filtrage ou de recherche :
        elle retourne l'intégralité des candidats de la structure.
    """

    authentication_classes = (
        authentication.TokenAuthentication,
        authentication.SessionAuthentication,
    )
    permission_classes = (ApplicantsAPIPermission,)
    serializer_class = ApplicantSerializer

    def get_queryset(self):
        # unique siae asserted by permission class
        siae_id = self.request.user.siaemembership_set.get().siae_id

        return (
            User.objects.filter(job_applications__to_siae_id=siae_id, is_job_seeker=True)
            .select_related("birth_place", "birth_country")
            .prefetch_related("job_applications")
            .order_by("-pk")
        )
