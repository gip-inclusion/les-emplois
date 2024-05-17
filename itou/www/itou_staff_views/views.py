import csv
import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import content_disposition_header

from itou.job_applications.models import JobApplication
from itou.utils.db import or_queries
from itou.www.itou_staff_views.export_utils import job_app_export_row, job_app_export_spec
from itou.www.itou_staff_views.forms import ItouStaffExportJobApplicationForm


class Echo:
    # https://docs.djangoproject.com/en/5.0/howto/outputting-csv/
    def write(self, value):
        return value


@login_required
def export_job_applications_unknown_to_ft(
    request,
    *args,
    template_name="itou_staff_views/export_job_applications_unknown_to_ft.html",
    **kwargs,
):
    """
    Internal self-service to export job applications of job seekers unknown to France Travail.
    """
    if not request.user.is_superuser:
        raise Http404

    form = ItouStaffExportJobApplicationForm(data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        departments = form.cleaned_data["departments"]
        tz = timezone.get_current_timezone()
        start = datetime.datetime.combine(form.cleaned_data["date_joined_from"], datetime.time.min, tz)
        end_date = form.cleaned_data["date_joined_to"] + datetime.timedelta(days=1)
        end = datetime.datetime.combine(end_date, datetime.time.min, tz)
        job_apps_qs = (
            JobApplication.objects.filter(
                or_queries(
                    [
                        Q(job_seeker__department=d) | Q(job_seeker__jobseeker_profile__hexa_post_code__startswith=d)
                        for d in departments
                    ]
                ),
                job_seeker__date_joined__gte=start,
                job_seeker__date_joined__lt=end,
                job_seeker__jobseeker_profile__pe_last_certification_attempt_at__isnull=False,
                job_seeker__jobseeker_profile__pe_obfuscated_nir__isnull=True,
            )
            .select_related(
                "to_company",
                "approval",
                "job_seeker__jobseeker_profile",
                "job_seeker__insee_city",
                "eligibility_diagnosis",
                "sender",
                "sender_company",
                "sender_prescriber_organization",
                "hired_job__appellation__rome",
                "hired_job__location",
            )
            .prefetch_related(
                "selected_jobs",
                "eligibility_diagnosis__administrative_criteria",
                "eligibility_diagnosis__author_prescriber_organization",
                "approval__prolongation_set",
                "approval__suspension_set",
            )
        )

        def content():
            yield job_app_export_spec.keys()
            for job_app in job_apps_qs:
                yield job_app_export_row(job_app)

        # Avoid exceedingly long filenames.
        departments_str = "multiple_departements" if len(departments) >= 5 else "_".join(departments)
        export_ts = f"{timezone.localdate().strftime('%Y-%m-%d')}_{timezone.localtime().strftime('%H-%M-%S')}"
        writer = csv.writer(Echo())
        return StreamingHttpResponse(
            content_type="text/csv",
            headers={
                "Content-Disposition": content_disposition_header(
                    as_attachment=True,
                    filename=f"candidats_emplois_inclusion_{departments_str}_non_certifies_{export_ts}.csv",
                ),
            },
            streaming_content=(writer.writerow(row) for row in content()),
        )
    return render(request, template_name, {"form": form})
