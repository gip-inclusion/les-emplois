import csv
import datetime
import io

from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseRedirect, StreamingHttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header

from itou.approvals.models import Approval
from itou.companies.models import CompanyMembership
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.utils.db import or_queries
from itou.utils.export import generate_excel_sheet
from itou.www.itou_staff_views.export_utils import (
    cta_export_spec,
    export_row,
    get_export_ts,
    job_app_export_spec,
)
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
                yield export_row(job_app_export_spec, job_app)

        # Avoid exceedingly long filenames.
        departments_str = "multiple_departements" if len(departments) >= 5 else "_".join(departments)
        writer = csv.writer(Echo())
        return StreamingHttpResponse(
            content_type="text/csv",
            headers={
                "Content-Disposition": content_disposition_header(
                    as_attachment=True,
                    filename=f"candidats_emplois_inclusion_{departments_str}_non_certifies_{get_export_ts()}.csv",
                ),
            },
            streaming_content=(writer.writerow(row) for row in content()),
        )
    return render(request, template_name, {"form": form})


@login_required
def export_ft_api_rejections(request):
    if not request.user.is_superuser:
        raise Http404

    first_day_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rejected_approvals = (
        Approval.objects.filter(
            pe_notification_status="notification_error",
            pe_notification_time__range=[
                first_day_of_month - relativedelta(months=1),
                first_day_of_month,
            ],
        )
        .select_related("user", "user__jobseeker_profile")
        .order_by("pe_notification_time")
    )

    if len(rejected_approvals) == 0:
        messages.add_message(request, messages.WARNING, "Pas de rejets de PASS IAE sur le dernier mois")
        return HttpResponseRedirect(reverse("dashboard:index"))

    data = []
    for approval in rejected_approvals:
        data.append(
            [
                approval.number,
                approval.pe_notification_time.isoformat(sep=" "),
                approval.pe_notification_exit_code,
                approval.user.jobseeker_profile.nir,
                approval.user.jobseeker_profile.pole_emploi_id,
                approval.user.last_name,
                approval.user.first_name,
                approval.user.jobseeker_profile.birthdate.isoformat(),
                approval.origin_siae_kind,
                approval.origin_siae_siret,
            ]
        )

    headers = [
        "numero",
        "date_notification",
        "code_echec",
        "nir",
        "pole_emploi_id",
        "nom_naissance",
        "prenom",
        "date_naissance",
        "siae_type",
        "siae_siret",
    ]

    workbook = generate_excel_sheet(headers, data)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"rejets_api_france_travail_{get_export_ts()}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@login_required()
def export_cta(request):
    if not request.user.is_superuser:
        raise Http404

    employees_qs = CompanyMembership.objects.active().select_related("company", "user")
    prescribers_qs = PrescriberMembership.objects.active().select_related("organization", "user")

    def content():
        yield cta_export_spec.keys()
        for employee in employees_qs.iterator():
            yield export_row(cta_export_spec, employee)
        for prescriber in prescribers_qs.iterator():
            yield export_row(cta_export_spec, prescriber)

    writer = csv.writer(Echo())
    return StreamingHttpResponse(
        content_type="text/csv",
        headers={
            "Content-Disposition": content_disposition_header(
                as_attachment=True,
                filename=f"export_cta_{get_export_ts()}.csv",
            ),
        },
        streaming_content=(writer.writerow(row) for row in content()),
    )
