import logging

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

JOB_SEEKER_IGNORED_RELATED_OBJECTS = [
    "logentry",
    "auth_token",
    "totpdevice",
    "emailaddress",
    "companymembership",
    "company",
    "jobseeker_profile",
    "prescribermembership",
    "prescriberorganization",
    "institution",
    "institutionmembership",
    "rdvi_invitation_requests",
    "rdvi_appointments",
    "rdvi_participations",
    "follow_up_group",
    "follow_up_groups_member",
    "follow_up_groups",
    "notification_settings",
    "jobseekerexternaldata",
    "externaldataimport",
    "eligibility_diagnoses",
    "geiq_eligibility_diagnoses",
    "approvals",
    "jobapplicationtransitionlog",
    "job_applications_sent",
    "job_applications",
]


def related_objects_to_check_for_jobseekers():
    return [
        rel
        for rel in User._meta.related_objects
        if (
            not rel.related_model._meta.proxy
            and not rel.related_model._meta.abstract
            and rel.name not in JOB_SEEKER_IGNORED_RELATED_OBJECTS
        )
    ]


def check_user_relations(rel, kind):
    count = rel.related_model.objects.filter(**{f"{rel.field.name}__kind": kind}).count()
    if count > 0:
        user_ids = (
            User.objects.filter(**{f"{rel.name}__isnull": False, "kind": kind}).values_list("id", flat=True).distinct()
        )
        logger.info(
            f"{rel.related_model.__name__} | {rel.name} | {count} undesired objects related | "
            f"{kind.value} ids: {list(user_ids)}"
        )


class Command(BaseCommand):
    def handle(self, *args, **options):
        logger.info("Starting unwanted related objects for jobseekers check...")
        related_objects = related_objects_to_check_for_jobseekers()
        for rel in related_objects:
            check_user_relations(rel, UserKind.JOB_SEEKER)

        logger.info("Check completed.")
