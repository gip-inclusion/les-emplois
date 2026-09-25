import re

from allauth.account.models import EmailAddress
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from itou.companies.models import CompanyMembership
from itou.institutions.models import InstitutionMembership
from itou.otp.models import ItouStaticDevice, ItouTOTPDevice
from itou.prescribers.models import PrescriberMembership
from itou.users.models import JobSeekerAssignment, User


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
