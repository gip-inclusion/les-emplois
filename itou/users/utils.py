import datetime
import logging
import re
from json import JSONDecodeError

import httpx
from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from itou.companies.models import CompanyMembership
from itou.institutions.models import InstitutionMembership
from itou.otp.models import ItouStaticDevice, ItouTOTPDevice
from itou.prescribers.models import PrescriberMembership
from itou.users.models import JobSeekerAssignment, User
from itou.utils.apis import api_particulier


logger = logging.getLogger(__name__)

# https://fr.wikipedia.org/wiki/Num%C3%A9ro_de_s%C3%A9curit%C3%A9_sociale_en_France#Signification_des_chiffres_du_NIR
NIR_RE = re.compile(
    """
    ^
    [0-9]      # sexe
    [0-9]{2}   # année de naissance
    [0-9]{2}   # mois de naissance
    [0-9]      # premier chiffre du département
    [0-9AB]  # deuxième chiffre du département
    [0-9]{3}   # lieu de naissance
    [0-9]{3}   # numéro d’ordre de naissance
    [0-9]{2}   # clé
    $""",
    re.IGNORECASE | re.VERBOSE,
)


def merge_job_seeker_assignments(*, assignment_to_delete, assignment_to_keep):
    last_assignment = max([assignment_to_delete, assignment_to_keep], key=lambda a: a.last_action_at)
    JobSeekerAssignment.objects.filter(pk=assignment_to_keep.pk).update(
        created_at=min(assignment_to_delete.created_at, assignment_to_keep.created_at),
        last_action_kind=last_assignment.last_action_kind,
        last_action_at=last_assignment.last_action_at,
        job_seeker=assignment_to_keep.job_seeker,
        ended_at=last_assignment.ended_at,
        end_reason=last_assignment.end_reason,
        reason=last_assignment.reason,
    )
    assignment_to_delete.delete()


def deactivate_users(users, *, updated_by=None):
    user_ids = [user.id for user in users]

    # `updated_at` is `auto_now`, but `auto_now` is only automatically updated when calling Model.save().
    # The field isn’t updated when making updates to other fields in other ways such as QuerySet.update()
    # https://docs.djangoproject.com/en/6.0/ref/models/fields/#django.db.models.DateField.auto_now
    # `updated_at` and `updated_by` are manually set otherwise the previous author would appear to be
    # the one deactivating the membership.
    now = timezone.now()
    for model in [CompanyMembership, InstitutionMembership, PrescriberMembership]:
        model.objects.filter(user_id__in=user_ids).update(
            is_active=False, is_admin=False, updated_by=updated_by, updated_at=now
        )

    EmailAddress.objects.filter(user_id__in=user_ids).delete()

    ItouTOTPDevice.objects.filter(user_id__in=user_ids).delete()
    ItouStaticDevice.objects.filter(user_id__in=user_ids).delete()

    # No need to keep assignments from professionals without organization or company.
    # If a professional was deactivated without deletion just because of an assignment
    # like these, he will be deleted on the next anonymization command run.
    JobSeekerAssignment.objects.filter(
        professional_id__in=user_ids,
        prescriber_organization_id__isnull=True,
        company_id__isnull=True,
    ).delete()

    User.objects.filter(id__in=user_ids).update(
        is_active=False,
        password=make_password(None),
        email=None,
        phone="",
        address_line_1="",
        address_line_2="",
        post_code="",
        city="",
        coords=None,
        insee_city=None,
    )

    for user in users:
        user.username = user.deactivated_username
    User.objects.bulk_update(users, ["username"])


RSA_CERTIFICATION_FRESHNESS = datetime.timedelta(hours=24)


def refresh_rsa_certification(job_seeker: User) -> None:
    """
    Ask API Particulier whether the job seeker currently benefits from the RSA, and store the
    answer on their profile.

    Deliberately side effect free with regards to the IAE eligibility diagnosis: unlike
    itou.eligibility.tasks.certify_criterion_with_api_particulier, no criterion, no
    IdentityCertification and none of the ASP fields (has_rsa_allocation, rsa_allocation_since)
    are touched.

    Never raises: when the API is unavailable, the fields are left as they are and displayed as
    missing information.
    """
    if settings.API_PARTICULIER_BASE_URL is None:
        logger.info("API particulier is not configured, RSA certification was skipped.")
        return

    profile = job_seeker.jobseeker_profile
    if not api_particulier.has_required_info(job_seeker):
        logger.info("Skipping job seeker %s, missing required information for API Particulier.", job_seeker.pk)
        return
    if (
        profile.rsa_certification_checked_at
        and timezone.now() - profile.rsa_certification_checked_at < RSA_CERTIFICATION_FRESHNESS
    ):
        return

    with api_particulier.client() as client:
        try:
            situation = api_particulier.fetch_rsa_situation(client, job_seeker)
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
            except JSONDecodeError:
                body = {}
            match exc.response.status_code:
                case 404 if "errors" in body:
                    # Found in the SNGI, but no “caisse de rattachement” ⇒ no subsidy.
                    situation = api_particulier.RSASituation(is_beneficiary=False, start_date=None)
                case 422 if "errors" in body:
                    # Identity not found, the query parameters would have to change.
                    situation = api_particulier.RSASituation(is_beneficiary=None, start_date=None)
                case _:
                    # 409, 429, 502 and any other error: retry on the next visit.
                    logger.warning(
                        "Could not refresh the RSA certification of job seeker %s, API Particulier "
                        "answered with HTTP %s.",
                        job_seeker.pk,
                        exc.response.status_code,
                    )
                    return
        except httpx.RequestError:
            logger.warning(
                "Could not refresh the RSA certification of job seeker %s, API Particulier is unreachable.",
                job_seeker.pk,
            )
            return

    profile.rsa_certified_beneficiary = situation.is_beneficiary
    profile.rsa_certified_start_date = situation.start_date
    profile.rsa_certification_checked_at = timezone.now()
    profile.save(
        update_fields=[
            "rsa_certified_beneficiary",
            "rsa_certified_start_date",
            "rsa_certification_checked_at",
        ]
    )
