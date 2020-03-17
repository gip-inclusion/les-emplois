from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.template.response import SimpleTemplateResponse
from django.utils.text import slugify
from django.utils.translation import gettext as _

from itou.job_applications.models import JobApplication
from itou.siaes.models import Siae
from itou.utils.pdf import HtmlToPdf


@login_required
def approval_as_pdf(request, job_application_id, template_name="approvals/approval_as_pdf.html"):

    siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
    queryset = Siae.active_objects.member_required(request.user)
    siae = get_object_or_404(queryset, pk=siae_pk)

    queryset = JobApplication.objects.select_related("job_seeker", "approval", "to_siae")
    job_application = get_object_or_404(queryset, pk=job_application_id, to_siae=siae)

    if not job_application.can_download_approval_as_pdf:
        raise Http404(
            _(
                """
            Nous sommes au regret de vous informer que
            vous ne pouvez pas télécharger cet agrément."""
            )
        )

    job_seeker = job_application.job_seeker
    user_name = job_seeker.get_full_name()

    diagnosis = None
    diagnosis_author = None
    diagnosis_author_org = None
    diagnosis_author_org_name = None

    # If an approval has been delivered by Pole Emploi, a diagnosis might
    # exist in the real world but not in our database.
    # Raise an error only if the diagnosis does not exist for an Itou approval.
    if job_application.approval.originates_from_itou:
        diagnosis = job_seeker.get_eligibility_diagnosis()
        diagnosis_author = diagnosis.author.get_full_name()
        diagnosis_author_org = diagnosis.author_prescriber_organization or diagnosis.author_siae
        if diagnosis_author_org:
            diagnosis_author_org_name = diagnosis_author_org.display_name

    # The PDFShift API can load styles only if it has
    # the full URL.
    base_url = request.build_absolute_uri("/")[:-1]

    if settings.DEBUG:
        # Use staging or production styles when working locally
        # as PDF shift can't access local files.
        base_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_STAGING_DN}"

    context = {
        "approval": job_application.approval,
        "base_url": base_url,
        "contact_email": settings.ITOU_EMAIL_CONTACT,
        "diagnosis_author": diagnosis_author,
        "diagnosis_author_org_name": diagnosis_author_org_name,
        "siae": job_application.to_siae,
        "user_name": user_name,
    }

    html = SimpleTemplateResponse(template=template_name, context=context).rendered_content

    filename = f"{slugify(user_name)}-pass-iae.pdf"

    with HtmlToPdf(html, autoclose=False) as transformer:
        return FileResponse(transformer.file, as_attachment=True, filename=filename)
