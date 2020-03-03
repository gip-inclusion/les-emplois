import io
from datetime import datetime as dt

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.template.response import SimpleTemplateResponse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.http import Http404, FileResponse
import pdfshift

from itou.job_applications.models import JobApplication


@login_required
def approval_as_pdf(
    request, job_application_id, template_name="approvals/approval_as_pdf.html"
):
    try:
        job_application = JobApplication.objects.select_related(
            "job_seeker", "approval", "to_siae"
        ).get(pk=job_application_id)

    except JobApplication.DoesNotExist:
        return Http404(
            _(
                """
            Nous sommes au regret de vous informer que la candidature reliée à cet agrément n'existe pas."""
            )
        )

    job_seeker = job_application.job_seeker
    user_name = job_seeker.get_full_name()

    diagnosis = job_seeker.eligibility_diagnoses.select_related(
        "author", "author_prescriber_organization", "author_siae"
    ).latest("created_at")
    diagnosis_author = diagnosis.author.get_full_name()
    diagnosis_author_org = (
        diagnosis.author_prescriber_organization or diagnosis.author_siae
    )

    if diagnosis_author_org:
        diagnosis_author_org = diagnosis_author_org.display_name

    approval = job_application.approval
    approval_has_started = approval.start_at <= dt.today().date()
    approval_has_ended = approval.end_at <= dt.today().date()

    # The PDFShift API can load styles only if it has
    # the full URL.
    base_url = request.build_absolute_uri("/")[:-1]

    if settings.DEBUG:
        # Use staging or production styles when working locally
        # as PDF shift can't access local files.
        base_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}"

    context = {
        "base_url": base_url,
        "approval_has_started": approval_has_started,
        "approval_has_ended": approval_has_ended,
        "approval": approval,
        "contact_email": settings.ITOU_EMAIL_CONTACT,
        "diagnosis_author": diagnosis_author,
        "diagnosis_author_org": diagnosis_author_org,
        "user_name": user_name,
        "siae": job_application.to_siae,
    }

    html = SimpleTemplateResponse(
        template=template_name, context=context
    ).rendered_content

    pdfshift.api_key = settings.PDFSHIFT_API_KEY
    binary_file = pdfshift.convert(html, sandbox=settings.PDFSHIFT_SANDBOX_MODE)

    buffer = io.BytesIO()
    buffer.write(binary_file)
    buffer.seek(0)

    filename = f"{slugify(user_name)}-pass-iae.pdf"

    return FileResponse(buffer, as_attachment=True, filename=filename)
