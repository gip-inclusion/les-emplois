import logging
import uuid
from functools import partial

from allauth.account.models import EmailAddress
from django.db import transaction
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from itou.common_apps.organizations.models import MembershipAbstract
from itou.communications.models import NotificationSettings
from itou.companies.models import CompanyMembership
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.gps.models import FollowUpGroupMembership
from itou.institutions.models import InstitutionMembership
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.users.utils import merge_job_seeker_assignments
from itou.utils.admin import add_support_remark_to_obj


logger = logging.getLogger(__name__)


def get_log_prefix(to_user, from_user):
    return f"Fusion utilisateurs {to_user.pk} ← {from_user.pk} — "


def get_users_relations():
    relations = []
    for rel in (
        field for field in User._meta.get_fields(include_hidden=True) if field.one_to_many or field.one_to_one
    ):
        couple = (rel.related_model, rel.field.name)
        if MODEL_MAPPING.get(couple) != noop:
            relations.append(couple)
    return sorted(relations, key=lambda t: (t[0].__module__, t[0].__name__, t[1]))


def admin_url(obj):
    try:
        return reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
    except NoReverseMatch:
        pass


def update_membership(from_user_membership, to_user_membership):
    to_user_membership.joined_at = min(to_user_membership.joined_at, from_user_membership.joined_at)
    to_user_membership.created_at = min(to_user_membership.created_at, from_user_membership.created_at)
    to_user_membership.is_admin |= from_user_membership.is_admin
    to_user_membership.is_active |= from_user_membership.is_active
    to_user_membership.updated_at = timezone.now()
    to_user_membership.updated_by = to_user_membership.updated_by or from_user_membership.updated_by
    to_user_membership.save()


def handle_membership(model, from_user, to_user, org_field_name=None):
    from_user_memberships = model.include_inactive.filter(user=from_user)
    updated_pks = []
    moved_pks = []
    for from_user_membership in from_user_memberships:
        if to_user_membership := model.include_inactive.filter(
            **{org_field_name: getattr(from_user_membership, org_field_name).pk, "user": to_user}
        ).first():
            updated_pks.append(to_user_membership.pk)
            update_membership(from_user_membership, to_user_membership)
        else:
            moved_pks.append(from_user_membership.pk)
            from_user_membership.user = to_user
            from_user_membership.save()
    base_log = get_log_prefix(to_user, from_user) + f"{model.__module__}.{model.__name__}.user"
    if updated_pks:
        logger.info(f"{base_log} updated : {updated_pks}")
    if moved_pks:
        logger.info(f"{base_log} moved : {moved_pks}")
    return len(from_user_memberships)


def handle_follow_up_group_membership(model, from_user, to_user):
    from_user_memberships = model.objects.filter(member=from_user)
    to_user_memberships = {
        membership.follow_up_group_id: membership for membership in model.objects.filter(member=to_user)
    }
    updated_pks = []
    moved_pks = []
    for from_user_membership in from_user_memberships:
        if to_user_membership := to_user_memberships.get(from_user_membership.follow_up_group_id):
            updated_pks.append(to_user_membership.pk)
            to_user_membership.is_referent_certified |= from_user_membership.is_referent_certified
            to_user_membership.is_active |= from_user_membership.is_active
            to_user_membership.created_at = min(to_user_membership.created_at, from_user_membership.created_at)
            to_user_membership.last_contact_at = max(
                to_user_membership.last_contact_at, from_user_membership.last_contact_at
            )
            to_user_membership.started_at = min(to_user_membership.started_at, from_user_membership.started_at)
            to_user_membership.can_view_personal_information |= from_user_membership.can_view_personal_information
            to_user_membership.reason = to_user_membership.reason or from_user_membership.reason
            to_user_membership.ended_at = to_user_membership.ended_at or from_user_membership.ended_at
            to_user_membership.end_reason = to_user_membership.end_reason or from_user_membership.end_reason
            # It's not perfect since we compare a date with the date of a datetime, but it's not a real issue
            if to_user_membership.ended_at and (
                to_user_membership.last_contact_at.date() > to_user_membership.ended_at
            ):
                to_user_membership.ended_at = None
                to_user_membership.end_reason = None
            to_user_membership.save()
        else:
            moved_pks.append(from_user_membership.pk)
            from_user_membership.member = to_user
            from_user_membership.save()

    base_log = get_log_prefix(to_user, from_user) + f"{model.__module__}.{model.__name__}.user"
    if updated_pks:
        logger.info(f"{base_log} updated : {updated_pks}")
    if moved_pks:
        logger.info(f"{base_log} moved : {moved_pks}")
    return len(from_user_memberships)


def handle_job_seeker_assignment(model, from_user, to_user):
    from_user_assignments = model.objects.filter(prescriber=from_user)
    to_user_assignments = {
        (assignment.job_seeker_id, assignment.prescriber_organization_id): assignment
        for assignment in model.objects.filter(prescriber=to_user)
    }
    updated_pks = []
    moved_pks = []
    for from_user_assignment in from_user_assignments:
        key = (
            from_user_assignment.job_seeker.pk,
            from_user_assignment.prescriber_organization.pk if from_user_assignment.prescriber_organization else None,
        )
        if to_user_assignment := to_user_assignments.get(key):
            updated_pks.append(to_user_assignment.pk)
            merge_job_seeker_assignments(
                assignment_to_delete=from_user_assignment, assignment_to_keep=to_user_assignment
            )
        else:
            moved_pks.append(from_user_assignment.pk)
            from_user_assignment.prescriber = to_user

    JobSeekerAssignment.objects.filter(pk__in=moved_pks).update(prescriber=to_user)
    base_log = get_log_prefix(to_user, from_user) + f"{model.__module__}.{model.__name__}.prescriber"
    if updated_pks:
        logger.info(f"{base_log} updated : {updated_pks}")
    if moved_pks:
        logger.info(f"{base_log} moved : {moved_pks}")
    return len(from_user_assignments)


def handle_token(model, from_user, to_user):
    if Token.objects.filter(user=to_user).exists():
        # We can't have more than one token per user so there's nothing to do
        return
    Token.objects.filter(user=from_user).update(user=to_user)


def noop(*args):
    return 0


MODEL_MAPPING = {
    (CompanyMembership, "user"): partial(handle_membership, org_field_name="company"),
    (PrescriberMembership, "user"): partial(handle_membership, org_field_name="organization"),
    (InstitutionMembership, "user"): noop,
    (EmailAddress, "user"): noop,
    (NotificationSettings, "user"): noop,
    (Token, "user"): handle_token,
    (FollowUpGroupMembership, "member"): handle_follow_up_group_membership,
    (JobSeekerAssignment, "prescriber"): handle_job_seeker_assignment,
    (User._meta.get_field("groups").remote_field.through, "user"): noop,
    (User._meta.get_field("user_permissions").remote_field.through, "user"): noop,
}

MODEL_REPR_MAPPING = {
    CompanyMembership: [
        lambda obj: f"<{obj.__class__.__name__}: {obj.user.get_full_name()} in {obj.company} ({obj.pk})>",
        [
            "user",
        ],
    ],
    PrescriberMembership: [
        lambda obj: f"<{obj.__class__.__name__}: {obj.user.get_full_name()} in {obj.organization} ({obj.pk})>",
        [
            "user",
        ],
    ],
    EligibilityDiagnosis: [
        lambda obj: f"<{obj.__class__.__name__}: for {obj.job_seeker.get_full_name()}>",
        [
            "job_seeker",
        ],
    ],
    GEIQEligibilityDiagnosis: [
        lambda obj: f"<{obj.__class__.__name__}: for {obj.job_seeker.get_full_name()}>",
        [
            "job_seeker",
        ],
    ],
    JobApplication: [
        lambda obj: f"<{obj.__class__.__name__}: {obj.pk} for {obj.job_seeker.get_full_name()}>",
        [
            "job_seeker",
        ],
    ],
}


def migrate_field(model, field_name, from_user, to_user):
    if func := MODEL_MAPPING.get((model, field_name)):
        func(model, from_user, to_user)
    else:
        if issubclass(model, MembershipAbstract):
            # Inactive objects must also be migrated to avoid RESTRICT errors on updated_by
            manager = model.include_inactive
        else:
            manager = model.objects
        pks = list(manager.filter(**{field_name: from_user}).values_list("pk", flat=True))
        if pks:
            if isinstance(pks[0], uuid.UUID):
                pks = "[" + ", ".join(str(pk) for pk in pks) + "]"
            logger.info(
                get_log_prefix(to_user, from_user) + f"{model.__module__}.{model.__name__}.{field_name} : {pks}"
            )
        manager.filter(**{field_name: from_user}).update(**{field_name: to_user})


@transaction.atomic
def merge_users(to_user, from_user, update_personal_data):
    assert to_user.kind in [UserKind.EMPLOYER, UserKind.PRESCRIBER]
    assert to_user.kind == from_user.kind
    support_remark = f"{timezone.localdate()}: Fusion des utilisateurs {to_user.email} et {from_user.email}"
    for model, field_name in get_users_relations():
        migrate_field(model, field_name, from_user, to_user)
    # Keep the most recent last_login to prevent the kept account from being archived
    to_user.last_login = max(filter(None, [to_user.last_login, from_user.last_login]), default=None)
    to_user.is_active |= from_user.is_active
    if update_personal_data:
        logger.info(get_log_prefix(to_user, from_user) + "Updated personal data")
        to_user.username = from_user.username
        to_user.email = from_user.email
        to_user.first_name = from_user.first_name
        to_user.last_name = from_user.last_name
        to_user.identity_provider = from_user.identity_provider
        # No need to update external_data_source_history, it will be done at next login
        add_support_remark_to_obj(to_user, support_remark + " en mettant à jour les infos personnelles")
    else:
        add_support_remark_to_obj(to_user, support_remark)
    final_log = get_log_prefix(to_user, from_user) + "Done !"
    _number, result = from_user.delete()
    deleted_models = set(result.keys())
    if forbidden_models := deleted_models - {
        "account.EmailAddress",
        "users.User",
        "gps.FollowUpGroupMembership",
        "communications.NotificationSettings",
        "prescribers.PrescriberMembership",
        "companies.CompanyMembership",
        "authtoken.Token",
    }:
        raise Exception(f"Forbidden models deleted : {forbidden_models}")
    to_user.save()
    logger.info(final_log)
