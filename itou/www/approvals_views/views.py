import io
from datetime import datetime as dt
from requests import exceptions as requests_exceptions

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, FileResponse
from django.shortcuts import get_object_or_404
from django.template.response import SimpleTemplateResponse
from django.utils.text import slugify
from django.utils.translation import gettext as _
import pdfshift

from itou.job_applications.models import JobApplication


@login_required
def approval_as_pdf(
    request, job_application_id, template_name="approvals/approval_as_pdf.html"
):
    queryset = JobApplication.objects.select_related(
        "job_seeker", "approval", "to_siae"
    )
    job_application = get_object_or_404(queryset, pk=job_application_id)

    if not job_application.has_a_downloadable_approval:
        raise Http404(
            _(
                """
            Nous sommes au regret de vous informer que
            vous ne pouvez pas télécharger cet agrément."""
            )
        )

    job_seeker = job_application.job_seeker
    user_name = job_seeker.get_full_name()

    diagnosis = job_seeker.get_eligibility_diagnosis()
    diagnosis_author = diagnosis.author.get_full_name()
    diagnosis_author_org = (
        diagnosis.author_prescriber_organization or diagnosis.author_siae
    )

    diagnosis_author_org_name = None
    if diagnosis_author_org:
        diagnosis_author_org_name = diagnosis_author_org.display_name

    approval = job_application.approval
    approval_has_started = approval.start_at <= dt.today().date()
    approval_has_ended = approval.end_at <= dt.today().date()

    # The PDFShift API can load styles only if it has
    # the full URL.
    base_url = request.build_absolute_uri("/")[:-1]

    if settings.DEBUG:
        # Use staging or production styles when working locally
        # as PDF shift can't access local files.
        base_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_STAGING_DN}"

    context = {
        "base_url": base_url,
        "approval_has_started": approval_has_started,
        "approval_has_ended": approval_has_ended,
        "approval": approval,
        "contact_email": settings.ITOU_EMAIL_CONTACT,
        "diagnosis_author": diagnosis_author,
        "diagnosis_author_org_name": diagnosis_author_org_name,
        "user_name": user_name,
        "siae": job_application.to_siae,
    }

    html = SimpleTemplateResponse(
        template=template_name, context=context
    ).rendered_content

    try:
        pdfshift.api_key = settings.PDFSHIFT_API_KEY
        binary_file = pdfshift.convert(html, sandbox=settings.PDFSHIFT_SANDBOX_MODE)
    except requests_exceptions.ConnectionError as error:
        # In Django 3 we can use RequestAborted here.
        raise ConnectionAbortedError(error)

    buffer = io.BytesIO()
    buffer.write(binary_file)
    buffer.seek(0)

    filename = f"{slugify(user_name)}-pass-iae.pdf"

    return FileResponse(buffer, as_attachment=True, filename=filename)
