from django.db.models import Exists, OuterRef, Prefetch
from django.utils import timezone

from itou.archive.models import AnonymizedProfessional
from itou.archive.utils import get_year_month_or_none
from itou.companies.models import CompanyMembership
from itou.institutions.models import InstitutionMembership
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.prescribers.models import PrescriberMembership
from itou.users.models import User
from itou.users.utils import deactivate_users
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


def deactivate_professionals_without_deletion(users):
    deactivate_users(users)

    text = f"{timezone.localtime().replace(microsecond=0)} - Désactivation/archivage de l'utilisateur"
    bulk_add_support_remark_to_objs(users, text)
