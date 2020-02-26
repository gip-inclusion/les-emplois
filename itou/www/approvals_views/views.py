import io

from django.utils.translation import gettext as _
from django.http import FileResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.pagesizes import A4

from itou.job_applications.models import JobApplication

def approval_as_pdf(request, job_application_id):
    page_width = A4[0]
    job_application = JobApplication.objects.select_related(
        "job_seeker",
        "approval",
        "to_siae",
    ).get(pk=job_application_id)
    user = job_application.job_seeker
    approval = job_application.approval
    # Create a file-like buffer to receive PDF data.
    buffer = io.BytesIO()

    # Create the PDF object, using the buffer as its "file."
    p = canvas.Canvas(buffer)

    # Draw things on the PDF. Here's where the PDF generation happens.
    # See the ReportLab documentation for the full list of functionality.

    import logging
    # handler = logging.StreamHandler(logging.stdout)
    logger = logging.getLogger(__name__)
    # logger.addHandler(handler)

    logger.warning("#########################################" + str(A4))

    p.drawString(260, 800, f"Agrément pour {user.get_full_name().title()}")
    p.drawString(100, 100, "Hello world.")

    # p.drawCentredString(x=100, text="texte")

    # Close the PDF object cleanly, and we're done.
    p.setTitle(_(f"Agrément pour {user.get_full_name().title()}"))
    p.showPage()
    p.save()

    # FileResponse sets the Content-Disposition header so that browsers
    # present the option to save the file.
    buffer.seek(0)
    # return FileResponse(buffer, as_attachment=True, filename='hello.pdf')
    return FileResponse(buffer, filename='hello.pdf')
