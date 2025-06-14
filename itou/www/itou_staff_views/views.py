import csv
import datetime
import io
from base64 import b32encode

import segno
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.db.models import Q
from django.http import FileResponse, HttpResponseRedirect, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import content_disposition_header
from django_otp import devices_for_user, login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.approvals.models import Approval
from itou.companies.models import CompanyMembership
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_user
from itou.utils.db import or_queries
from itou.utils.export import generate_excel_sheet
from itou.www.itou_staff_views import merge_utils
from itou.www.itou_staff_views.export_utils import (
    cta_export_spec,
    export_row,
    get_export_ts,
    job_app_export_spec,
)
from itou.www.itou_staff_views.forms import (
    ConfirmTOTPDeviceForm,
    ItouStaffExportJobApplicationForm,
    MergeUserConfirmForm,
    MergeUserForm,
)


class Echo:
    # https://docs.djangoproject.com/en/5.0/howto/outputting-csv/
    def write(self, value):
        return value


@check_user(lambda user: user.is_staff)
@permission_required("job_applications.export_job_applications_unknown_to_ft")
def export_job_applications_unknown_to_ft(
    request,
    *args,
    template_name="itou_staff_views/export_job_applications_unknown_to_ft.html",
    **kwargs,
):
    """
    Internal self-service to export job applications of job seekers unknown to France Travail.
    """
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


@check_user(lambda user: user.is_staff)
@permission_required("approvals.export_ft_api_rejections")
def export_ft_api_rejections(request):
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
        messages.add_message(request, messages.WARNING, "Pas de rejets de PASS IAE sur le dernier mois")
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


@check_user(lambda user: user.is_staff)
@permission_required("users.export_cta")
def export_cta(request):
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


@check_user(lambda user: user.is_staff)
@permission_required("users.merge_users")
def merge_users(request, template_name="itou_staff_views/merge_users.html"):
    form = MergeUserForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        return HttpResponseRedirect(
            reverse(
                "itou_staff_views:merge_users_confirm",
                kwargs={"user_1_public_id": form.user_1.public_id, "user_2_public_id": form.user_2.public_id},
            )
        )

    return render(request, template_name, {"form": form})


@check_user(lambda user: user.is_staff)
@permission_required("users.merge_users")
def merge_users_confirm(
    request, user_1_public_id, user_2_public_id, template_name="itou_staff_views/merge_users_confirm.html"
):
    ALLOWED_USER_KINDS = [UserKind.PRESCRIBER, UserKind.EMPLOYER]

    user_1 = get_object_or_404(User, public_id=user_1_public_id)
    user_2 = get_object_or_404(User, public_id=user_2_public_id)

    # Always put the oldest user (with the smallest pk) on the left side
    to_user, from_user = sorted([user_1, user_2], key=lambda user: user.id)

    to_user_error = None
    from_user_error = None
    transfer_data = []
    merge_allowed = False

    # checks
    if to_user.kind != from_user.kind:
        to_user_error = from_user_error = "Les utilisateurs doivent être du même type"
    if to_user == from_user:
        to_user_error = from_user_error = "Les utilisateurs doivent être différents"
    if to_user.kind not in ALLOWED_USER_KINDS:
        to_user_error = "L’utilisateur doit être employeur ou prescripteur"
    if from_user.kind not in ALLOWED_USER_KINDS:
        from_user_error = "L’utilisateur doit être employeur ou prescripteur"

    form = MergeUserConfirmForm(data=request.POST or None)

    if to_user_error is None and from_user_error is None:
        merge_allowed = True
        if request.method == "POST" and form.is_valid():
            try:
                success_message = format_html(
                    'Fusion {} & {} effectuée : (<a href="{}">admin</a>)',
                    to_user.email,
                    from_user.email,
                    merge_utils.admin_url(to_user),
                )
                merge_utils.merge_users(
                    to_user,
                    from_user,
                    update_personal_data=form.cleaned_data["user_to_keep"] == "from_user",
                )
                messages.success(request, success_message)
                return HttpResponseRedirect(reverse("itou_staff_views:merge_users"))
            except Exception as e:
                messages.error(request, f"Erreur survenue: {e}")
                return HttpResponseRedirect(
                    reverse(
                        "itou_staff_views:merge_users_confirm",
                        kwargs={"user_1_public_id": to_user.public_id, "user_2_public_id": from_user.public_id},
                    )
                )

        for model, field_name in merge_utils.get_users_relations():
            repr_func, related = merge_utils.MODEL_REPR_MAPPING.get(model, (repr, []))
            data = [
                (repr_func(obj), merge_utils.admin_url(obj))
                for obj in model.objects.filter(**{field_name: from_user}).select_related(*related).iterator()
            ]
            if data:
                transfer_data.append((f"{model.__name__}.{field_name}", f"{model.__module__}.{model.__name__}", data))

    context = {
        "to_user": to_user,
        "to_user_admin_link": merge_utils.admin_url(to_user),
        "to_user_error": to_user_error,
        "from_user": from_user,
        "from_user_admin_link": merge_utils.admin_url(from_user),
        "from_user_error": from_user_error,
        "merge_allowed": merge_allowed,
        "transfer_data": transfer_data,
        "form": form,
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_staff)
def otp_devices(request, template_name="itou_staff_views/otp_devices.html"):
    if request.method == "POST":
        if request.POST.get("action") == "new":
            device, _ = TOTPDevice.objects.get_or_create(user=request.user, confirmed=False)
            return HttpResponseRedirect(
                reverse("itou_staff_views:otp_confirm_device", kwargs={"device_id": device.pk})
            )
        if device_id := request.POST.get("delete-device"):
            device = get_object_or_404(TOTPDevice.objects.filter(user=request.user), pk=device_id)
            if device != request.user.otp_device:
                messages.success(request, "L’appareil a été supprimé.")
                device.delete()
            else:
                messages.error(request, "Impossible de supprimer l’appareil qui a été utilisé pour se connecter.")

    context = {"devices": sorted(devices_for_user(request.user), key=lambda device: device.created_at)}
    return render(request, template_name, context)


@check_user(lambda user: user.is_staff)
def otp_confirm_device(request, device_id, template_name="itou_staff_views/otp_confirm_device.html"):
    device = get_object_or_404(TOTPDevice.objects.filter(user=request.user, confirmed=False), pk=device_id)

    form = ConfirmTOTPDeviceForm(data=request.POST or None, device=device)
    if request.method == "POST" and form.is_valid():
        device.confirmed = True
        device.name = form.cleaned_data["name"]
        device.save(update_fields=["name", "confirmed"])
        messages.success(request, "Votre nouvel appareil est confirmé", extra_tags="toast")
        # Mark the user as verified
        otp_login(request, device)
        return HttpResponseRedirect(reverse("itou_staff_views:otp_devices"))

    context = {
        "form": form,
        "otp_secret": b32encode(device.bin_key).decode(),
        # Generate svg data uri qrcode
        "qrcode": segno.make(device.config_url).svg_data_uri(),
        "otp_verified": False,
    }
    return render(request, template_name, context)
