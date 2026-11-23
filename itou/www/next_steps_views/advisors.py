"""The job seeker's records the user may see, as the matching tabs of the existing job seeker page show them."""

from django.db.models import Exists, OuterRef, Value

from itou.job_applications.models import JobApplication
from itou.job_applications.utils import xp_ref_iae_job_applications
from itou.www.job_seekers_views.views import can_view_external_actions


def _job_applications(request, job_seeker):
    """Same scopes as job_seekers_views.JobApplicationTabView.get_job_applications."""
    if request.from_employer:
        scoped = JobApplication.objects.for_company(request.current_organization).filter(job_seeker=job_seeker)
    else:
        scoped = job_seeker.job_applications.prescriptions_of(
            request.user, request.current_organization
        ) | xp_ref_iae_job_applications(request).filter(job_seeker=job_seeker)
    if can_view_external_actions(job_seeker, request):
        return job_seeker.job_applications.annotate(user_can_see_details=Exists(scoped.filter(pk=OuterRef("pk"))))
    return scoped.annotate(user_can_see_details=Value(True))
