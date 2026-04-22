import contextlib
import time
from math import ceil

from django.core.exceptions import ValidationError
from itoutils.django.nexus.token import generate_token

from itou.users.enums import UserKind
from itou.users.models import User
from itou.users.perms import can_prefill_orientation_on_dora


def get_orientation_jwt(request) -> str | None:
    if not can_prefill_orientation_on_dora(request):
        return None

    job_seeker = None
    if job_seeker_uid := request.GET.get("job_seeker_public_id"):
        with contextlib.suppress(User.DoesNotExist, ValidationError):
            job_seeker = User.objects.select_related("jobseeker_profile").get(
                kind=UserKind.JOB_SEEKER, public_id=job_seeker_uid
            )

    jwt_claims = {
        "exp": ceil(time.time()) + 3600,
        "prescriber": {
            "email": request.user.email,
            "organization": {
                "siret": request.current_organization.siret,
                "uid": str(request.current_organization.uid),
            },
        },
    }
    if job_seeker:
        jwt_claims["beneficiary"] = {
            "uid": str(job_seeker.public_id),
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "email": job_seeker.email,
            "phone": job_seeker.phone,
            "france_travail_id": job_seeker.jobseeker_profile.pole_emploi_id,
        }
    return generate_token(jwt_claims)
