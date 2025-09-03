import datetime

from django.db import models
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.gps.models import FollowUpGroupMembership
from itou.job_applications.models import JobApplication
from itou.siae_evaluations.models import EvaluatedJobApplication
from itou.users.models import User, UserKind


def get_filter_kwargs_on_user_for_related_objects_to_check():
    """
    Returns a dictionary of filter parameters to check for objects related
    to the User model that are not cascade deleted.
    """
    return {
        f"{obj.name}__isnull": True
        for obj in User._meta.related_objects
        if getattr(obj, "on_delete", None) and obj.on_delete != models.CASCADE
    }


def get_year_month_or_none(date=None):
    if not date:
        return None

    if isinstance(date, datetime.datetime):
        return timezone.localdate(date).replace(day=1)

    return date.replace(day=1)


def count_related_subquery(model, fk_field, outer_ref_field, extra_filters=None):
    filters = {fk_field: OuterRef(outer_ref_field)}
    if extra_filters:
        filters.update(extra_filters)
    return Coalesce(
        model.objects.filter(**filters).values(fk_field).annotate(count=Count(outer_ref_field)).values("count"), 0
    )


def inactive_jobseekers_without_recent_related_objects(inactive_since, notified, batch_size=None):
    recent_approval = Approval.objects.filter(end_at__gt=inactive_since, user_id=OuterRef("pk"))
    recent_eligibility_diagnosis = EligibilityDiagnosis.objects.filter(
        expires_at__gt=inactive_since, job_seeker_id=OuterRef("pk")
    )
    recent_geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.filter(
        expires_at__gt=inactive_since, job_seeker_id=OuterRef("pk")
    )
    recent_job_application = JobApplication.objects.filter(
        Q(created_at__gt=inactive_since) | Q(logs__timestamp__gt=inactive_since),
        job_seeker_id=OuterRef("pk"),
    )
    recent_followup_group_contact = FollowUpGroupMembership.objects.filter(
        follow_up_group__beneficiary_id=OuterRef("pk"), last_contact_at__gt=inactive_since
    )
    evaluated_job_application = EvaluatedJobApplication.objects.filter(job_application__job_seeker_id=OuterRef("pk"))

    qs = (
        User.objects.filter(
            (Q(last_login__lte=inactive_since) | Q(last_login__isnull=True)),
            date_joined__lte=inactive_since,
            kind=UserKind.JOB_SEEKER,
            upcoming_deletion_notified_at__isnull=not notified,
        )
        .filter(
            ~Exists(recent_approval),
            ~Exists(recent_eligibility_diagnosis),
            ~Exists(recent_geiq_eligibility_diagnosis),
            ~Exists(recent_job_application),
            ~Exists(recent_followup_group_contact),
            ~Exists(evaluated_job_application),
        )
        .order_by("date_joined", "pk")
    )

    if batch_size:
        return qs[:batch_size]

    return qs
