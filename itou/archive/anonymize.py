from allauth.account.models import EmailAddress
from django.contrib.auth.hashers import make_password
from django.db.models import Exists, OuterRef, Prefetch
from django.utils import timezone

from itou.archive.models import AnonymizedProfessional
from itou.archive.utils import get_year_month_or_none
from itou.companies.models import CompanyMembership
from itou.institutions.models import InstitutionMembership
from itou.otp.models import ItouStaticDevice, ItouTOTPDevice
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.prescribers.models import PrescriberMembership
from itou.users.models import JobSeekerAssignment, User
from itou.utils.admin import bulk_add_support_remark_to_objs


def annotate_and_prefetch_for_anonymization(users_qs):
    has_membership_in_authorized_organization_sqs = PrescriberMembership.include_inactive.filter(
        user_id=OuterRef("id"), organization__authorization_status=PrescriberAuthorizationStatus.VALIDATED
    )
    return users_qs.annotate(
        has_membership_in_authorized_organization=Exists(has_membership_in_authorized_organization_sqs)
    ).prefetch_related(
        Prefetch(
            "companymembership_set",
            to_attr="prefetched_companymemberships",
            queryset=CompanyMembership.include_inactive.all(),
        ),
        Prefetch(
            "prescribermembership_set",
            to_attr="prefetched_prescribermemberships",
            queryset=PrescriberMembership.include_inactive.all(),
        ),
        Prefetch(
            "institutionmembership_set",
            to_attr="prefetched_institutionmemberships",
            queryset=InstitutionMembership.include_inactive.all(),
        ),
    )


def _make_anonymized_professional(user):
    memberships = [
        *user.prefetched_companymemberships,
        *user.prefetched_institutionmemberships,
        *user.prefetched_prescribermemberships,
    ]
    return AnonymizedProfessional(
        date_joined=get_year_month_or_none(user.date_joined),
        first_login=get_year_month_or_none(user.first_login),
        last_login=get_year_month_or_none(user.last_login),
        department=user.department,
        title=user.title,
        kind=user.kind,
        number_of_memberships=len(memberships),
        number_of_active_memberships=sum(m.is_active for m in memberships),
        number_of_memberships_as_administrator=sum(m.is_admin for m in memberships),
        had_memberships_in_authorized_organization=user.has_membership_in_authorized_organization,
        identity_provider=user.identity_provider,
    )


def anonymize_and_delete_professionals(users):
    AnonymizedProfessional.objects.bulk_create([_make_anonymized_professional(user) for user in users])
    User.objects.filter(id__in=[user.id for user in users]).delete()


def anonymize_professionals_without_deletion(users):
    user_ids = [user.id for user in users]

    # `updated_at` is `auto_now`, but `auto_now` is only automatically updated when calling Model.save().
    # The field isn’t updated when making updates to other fields in other ways such as QuerySet.update()
    # https://docs.djangoproject.com/en/6.0/ref/models/fields/#django.db.models.DateField.auto_now
    # `updated_at` and `updated_by` are manually reset otherwise the previous author would appear to be
    # the one deactivating the membership.
    now = timezone.now()
    for model in [CompanyMembership, InstitutionMembership, PrescriberMembership]:
        model.objects.filter(user_id__in=user_ids).update(
            is_active=False, is_admin=False, updated_by=None, updated_at=now
        )

    EmailAddress.objects.filter(user_id__in=user_ids).delete()

    ItouTOTPDevice.objects.filter(user_id__in=user_ids).delete()
    ItouStaticDevice.objects.filter(user_id__in=user_ids).delete()

    # No need to keep assignments from professionals without organization or company.
    # If a professional was anonymized without deletion just because of an assignment
    # like these, he will be deleted on the next command run.
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

    text = f"{timezone.localtime().replace(microsecond=0)} - Désactivation/archivage de l'utilisateur"
    bulk_add_support_remark_to_objs(users, text)
