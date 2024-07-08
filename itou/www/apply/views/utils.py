from django.shortcuts import get_object_or_404

from itou.users.enums import UserKind
from itou.users.models import User


def get_job_seeker_public_id(job_seeker_pk):
    """
    Temporary need for the conversion of primary key to public_id on a job_seeker
    """
    return get_object_or_404(
        User.objects.filter(kind=UserKind.JOB_SEEKER),
        pk=job_seeker_pk,
    ).public_id
