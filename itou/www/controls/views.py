from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

# from django.core.exceptions import PermissionDenied
from django.urls import reverse

from itou.job_applications.models import JobApplication
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.urls import get_safe_url


@login_required
def review_self_approvals(request, template_name="controls/review_self_approvals.html"):
    institution = get_current_institution_or_404(request)
    context = {
        "institution": institution,
    }
    return render(request, template_name, context)


@login_required
def self_approvals_list(request, template_name="controls/self_approvals_list.html"):
    siae = get_current_siae_or_404(request)

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))
    context = {
        "siae": siae,
        "approval_list": [1, 2],
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def self_approvals(request, approval_id, template_name="controls/self_approvals.html"):
    siae = get_current_siae_or_404(request)
    queryset = JobApplication.objects.select_related("job_seeker", "eligibility_diagnosis", "approval", "to_siae")
    job_application = get_object_or_404(queryset, approval_id=approval_id, to_siae=siae)

    context = {"siae": siae, "job_application": job_application}
    return render(request, template_name, context)
