from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Exists, OuterRef, Q
from rest_framework import authentication, generics
from rest_framework.exceptions import ValidationError

from itou.api import AUTH_TOKEN_EXPLANATION_TEXT
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.models import User

from .perms import ApplicantsAPIPermission
from .serializers import APIParametersSerializer, ApplicantSerializer


class ApplicantsView(generics.ListAPIView):
    authentication_classes = (
        authentication.TokenAuthentication,
        authentication.SessionAuthentication,
    )
    permission_classes = (ApplicantsAPIPermission,)
    serializer_class = ApplicantSerializer

    def get_queryset(self):
        serializer = APIParametersSerializer(data=self.request.query_params)
        if not serializer.is_valid():
            raise ValidationError

        multi_companies_mode = serializer.validated_data.get("mode_multi_structures", False)
        companies_uids_params = serializer.validated_data.get("uid_structures", [])
        memberships = (
            self.request.user.active_or_in_grace_period_company_memberships()
            .order_by("created_at")
            .values("company_id", "company__uid")
        )
        if companies_uids_params:
            companies_ids = [
                membership["company_id"]
                for membership in memberships
                if str(membership["company__uid"]) in companies_uids_params
            ]
        else:
            companies_ids = [membership["company_id"] for membership in memberships]

        if not multi_companies_mode and not companies_uids_params:
            # Legacy behaviour.
            # Return the first membership available.
            companies_ids = companies_ids[:1]

        return (
            User.objects.filter(
                Exists(
                    JobApplication.objects.filter(
                        job_seeker_id=OuterRef("pk"),
                        to_company_id__in=companies_ids,
                    )
                ),
                kind=UserKind.JOB_SEEKER,
            )
            .annotate(
                companies_uids=ArrayAgg(
                    "job_applications__to_company_id__uid",
                    filter=Q(job_applications__to_company_id__in=companies_ids),
                    distinct=True,
                    ordering="job_applications__to_company_id__uid",
                )
            )
            .select_related("jobseeker_profile__birth_place", "jobseeker_profile__birth_country")
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

Le compte administrateur utilisé peut être membre administrateur d'une ou de plusieurs structures.
Par défaut, l'API renvoie les candidatures reçues par la première structure dont le compte est membre
car la première version avait été pensée ainsi.

# Paramètres

- mode_multi_structures : renvoie les candidats de toutes les structures.
- uid_structures : renvoie les candidats des structures demandées.

Attention, le compte doit être administrateur de toutes les structures dont il est membre.

# Exemples de requêtes

## Mode multistructures

```bash
curl
-L '{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/api/v1/candidats/?mode_multi_structures=1' \
-H 'Authorization: Token [token]'
```

## Fitre par structure

Afin de trouver l'identifiant unique d'une structure, connectez-vous à votre espace personnel
et cliquez sur « Mon espace » > « Accès aux APIs ».

### Une structure

```bash
curl
'{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/api/v1/candidats/?structures_uid=<uid_1>' \
--header 'Authorization: Token [token]'
```

### Plusieurs structures

Séparez les identifiants par des virgules.

```bash
curl
'{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/api/v1/candidats/?structures_uid=<uid_1>,<uid_2>' \
--header 'Authorization: Token [token]'
```

"""
