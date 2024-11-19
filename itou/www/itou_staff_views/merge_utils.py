import logging
import uuid
from functools import partial

from allauth.account.models import EmailAddress
from django.db import transaction
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from itou.communications.models import NotificationSettings
from itou.companies.models import CompanyMembership
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.institutions.models import InstitutionMembership
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.admin import add_support_remark_to_obj


logger = logging.getLogger(__name__)


def get_log_prefix(to_user, from_user):
    return f"Fusion utilisateurs {to_user.pk} ← {from_user.pk} — "


def get_users_relations():
    relations = []
    for rel in (rel for rel in User._meta.get_fields() if rel.auto_created and not rel.concrete):
        if getattr(rel, "through", None):
            # ManyToMany relation, we will use the ManyToOne relation from the through model instead
            continue
        couple = (rel.related_model, rel.field.name)
        if MODEL_MAPPING.get(couple) != noop:
            relations.append(couple)

    # JobApplication.archived_by does not have a backward relation because of related_name="+"
    relations.append((JobApplication, "archived_by"))

    return sorted(relations, key=lambda t: (t[0].__module__, t[0].__name__, t[1]))


def admin_url(obj):
    try:
        return reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.id])
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
    from_user_memberships = model.objects.filter(user=from_user)
    updated_pks = []
    moved_pks = []
    for from_user_membership in from_user_memberships:
        if to_user_membership := model.objects.filter(
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


def noop(*args):
    return 0


MODEL_MAPPING = {
    (CompanyMembership, "user"): partial(handle_membership, org_field_name="company"),
    (PrescriberMembership, "user"): partial(handle_membership, org_field_name="organization"),
    (InstitutionMembership, "user"): noop,
    (EmailAddress, "user"): noop,
    (NotificationSettings, "user"): noop,
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
        pks = list(model.objects.filter(**{field_name: from_user}).values_list("pk", flat=True))
        if pks:
            if isinstance(pks[0], uuid.UUID):
                pks = "[" + ", ".join(str(pk) for pk in pks) + "]"
            logger.info(
                get_log_prefix(to_user, from_user) + f"{model.__module__}.{model.__name__}.{field_name} : {pks}"
            )
        model.objects.filter(**{field_name: from_user}).update(**{field_name: to_user})


@transaction.atomic
def merge_users(to_user, from_user, update_personal_data):
    assert to_user.kind in [UserKind.EMPLOYER, UserKind.PRESCRIBER]
    assert to_user.kind == from_user.kind
    support_remark = f"{timezone.localdate()}: Fusion d'utilisateurs {to_user.email} ← {from_user.email}"
    for model, field_name in get_users_relations():
        migrate_field(model, field_name, from_user, to_user)
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
        "communications.NotificationSettings",
        "prescribers.PrescriberMembership",
        "companies.CompanyMembership",
    }:
        raise Exception(f"Forbidden models deleted : {forbidden_models}")
    to_user.save()
    logger.info(final_log)
