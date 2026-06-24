import contextlib
import time
from math import ceil

from django.core.exceptions import ValidationError
from django.urls import reverse
from itoutils.django.nexus.token import generate_token

from itou.users.enums import UserKind
from itou.users.models import User
from itou.users.perms import can_orient_towards_insertion_service
from itou.utils.perms.utils import can_view_personal_information
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


def get_orient_for_job_seeker_context(request) -> dict:
    job_seeker = None
    exit_url = reverse("home:hp")
    can_view = False

    if can_orient_towards_insertion_service(request):
        if request.from_prescriber:
            exit_url = reverse("job_seekers_views:list")
        elif request.from_employer:
            exit_url = reverse("job_seekers_views:list_organization")

        job_seeker = get_job_seeker_from_request(request)
        if job_seeker:
            can_view = can_view_personal_information(request, job_seeker)

    return {
        "job_seeker": job_seeker,
        "exit_url": exit_url,
        "can_view_personal_information": can_view,
        "can_orient_towards_insertion_service": can_orient_towards_insertion_service(request),
    }


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
