from datetime import datetime as dt

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from django.shortcuts import render
from django.http import Http404
# from django.http import FileResponse

from itou.job_applications.models import JobApplication

@login_required
def approval_as_pdf(request,
                    job_application_id,
                    template_name="approvals/approval_as_pdf.html"):
    try:
        job_application = JobApplication.objects.select_related(
            "job_seeker",
            "approval",
            "to_siae",
        ).get(pk=job_application_id)

    except JobApplication.DoesNotExist:
        return Http404(_("""
            Nous sommes au regret de vous informer que la candidature reliée à cet agrément n'existe pas."""
        ))

    job_seeker = job_application.job_seeker
    user_name = job_seeker.get_full_name()
    diagnosis = job_seeker.eligibility_diagnoses.latest("created_at")
    diagnosis_author = diagnosis.author.get_full_name()
    diagnosis_author_org = diagnosis.author_prescriber_organization or diagnosis.author_siae
    diagnosis_author_org = diagnosis_author_org.display_name

    approval = job_application.approval
    approval_has_started = approval.start_at <= dt.today().date()
    approval_has_ended = approval.end_at <= dt.today().date()

    context = {
        "approval_has_started": approval_has_started,
        "approval_has_ended": approval_has_ended,
        "approval": approval,
        "contact_email": settings.ITOU_EMAIL_CONTACT,
        "diagnosis_author": diagnosis_author,
        "diagnosis_author_org": diagnosis_author_org,
        "user_name": user_name,
        "siae": job_application.to_siae,
    }

    return render(request, template_name, context)
