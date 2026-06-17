import contextlib
import time
from math import ceil

from django.core.exceptions import ValidationError
from itoutils.django.nexus.token import generate_token

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.phone import normalize_phone_number


def get_missing_orientation_beneficiary_field_labels(job_seeker: User) -> list[str]:
    missing = []
    if not job_seeker.first_name or not job_seeker.first_name.strip():
        missing.append("Prénom")
    if not job_seeker.last_name or not job_seeker.last_name.strip():
        missing.append("Nom")
    if not job_seeker.email or not job_seeker.email.strip():
        missing.append("Adresse e-mail")
    if not normalize_phone_number(job_seeker.phone or ""):
        missing.append("Téléphone")
    return missing


def get_job_seeker_from_request(request) -> User | None:
    if job_seeker_uid := request.GET.get("job_seeker_public_id"):
        with contextlib.suppress(ValidationError):
            return (
                User.objects.select_related("jobseeker_profile")
                .filter(kind=UserKind.JOB_SEEKER, public_id=job_seeker_uid)
                .first()
            )
    return None


def get_orientation_jwt(request) -> str | None:
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

    job_seeker = get_job_seeker_from_request(request)

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
