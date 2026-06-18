import base64
import binascii
import logging

import segno
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic.edit import FormView
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import default_key as generate_otp_key

from itou.otp.models import ItouStaticDevice, ItouTOTPDevice
from itou.otp.utils import create_otp_backup_code, get_user_devices, notify_backup_code_has_been_used
from itou.utils.auth import check_user
from itou.utils.readonly import http_methods
from itou.utils.urls import get_safe_url
from itou.www.otp_views.enums import DeviceType
from itou.www.otp_views.forms import ConfirmTOTPDeviceForm, LoginWithBackupCodeForm, VerifyOTPForm


logger = logging.getLogger(__name__)
check_user_for_otp = check_user(lambda user: user.is_staff or user.is_professional)


@http_methods(db_readonly=["GET", "HEAD"], db_write=["POST"])
@check_user_for_otp
def otp_devices(request, template_name="otp_views/otp_devices.html"):
    devices = get_user_devices(request.user)
    if request.method == "POST":
        if device_id := request.POST.get("delete-device"):
            device = get_object_or_404(ItouTOTPDevice.objects.filter(user=request.user), pk=device_id)
            if device != request.user.otp_device:
                messages.success(request, "L’appareil a été supprimé.")
                device.delete()
                devices = get_user_devices(request.user)
            else:
                messages.error(request, "Impossible de supprimer l’appareil qui a été utilisé pour se connecter.")

    context = {"devices": devices}
    return render(request, template_name, context)


@check_user_for_otp
def enrollment_step_0_intro(request, template_name="otp_views/enrollment_step_0_intro.html"):
    context = {"next_step_url": reverse("otp_views:enrollment_step_1_choose_device_type")}
    return render(request, template_name, context)


@check_user_for_otp
def enrollment_step_1_choose_device_type(request, template_name="otp_views/enrollment_step_1_choose_device_type.html"):
    context = {"next_step_url": reverse("otp_views:enrollment_step_2_and_3_confirm_device")}
    return render(request, template_name, context)


@http_methods(db_readonly=["GET", "HEAD"], db_write=["POST"])
@check_user_for_otp
def enrollment_step_2_and_3_confirm_device(
    request, template_name="otp_views/enrollment_step_2_and_3_confirm_device.html"
):
    previous_step_url = reverse("otp_views:enrollment_step_1_choose_device_type")
    device_type = request.GET.get("device_type") or request.POST.get("device_type")
    if device_type not in DeviceType:
        # should not happen, unless user manipulates the request
        return HttpResponseRedirect(previous_step_url)

    device = ItouTOTPDevice(
        user=request.user,
        key=binascii.hexlify(base64.b32decode(request.POST["key"].encode())).decode()
        if request.POST
        else generate_otp_key(),
    )

    backup_code = None
    post_save_url = None
    form = ConfirmTOTPDeviceForm(
        data=request.POST or None,
        device_type=device_type,
        device=device,
    )
    if request.method == "POST":
        if not form.is_valid():
            # Form calls `device.verify_token()` that saves the
            # object. If the form is not valid, the object is useless,
            # we can delete it.
            device.delete()
        else:
            device.name = form.cleaned_data["name"]
            device.save()
            messages.success(request, "Votre nouvel appareil est confirmé", extra_tags="toast")
            otp_login(request, device)  # mark the user as verified
            backup_code = create_otp_backup_code(request.user)
            if len(get_user_devices(request.user)) > 1:
                # User added _another_ device, redirect user to where they
                # come from.
                post_save_url = reverse("otp_views:otp_devices")
            else:
                # User added their _only_ device (required to use the
                # application), they want to use the app.
                post_save_url = reverse("dashboard:index")

    context = {
        "previous_step_url": previous_step_url,
        "form": form,
        "otp_secret": form.fields["key"].initial,
        "qrcode": segno.make(device.config_url).svg_data_uri(),
        "backup_code": backup_code,
        "post_save_url": post_save_url,
    }
    return render(request, template_name, context)


class VerifyOTPView(FormView):
    template_name = "otp_views/verify_otp.html"
    form_class = VerifyOTPForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        devices = get_user_devices(self.request.user)
        return context | {"devices": devices}

    def get_form_kwargs(self):
        return super().get_form_kwargs() | {"user": self.request.user}

    def form_valid(self, form):
        otp_login(self.request, self.request.user.otp_device)
        return super().form_valid(form)

    def get_success_url(self):
        return get_safe_url(self.request, REDIRECT_FIELD_NAME, reverse("dashboard:index"))


@check_user_for_otp
def login_with_backup_code(request, template_name="otp_views/login_with_backup_code.html"):
    static_device = ItouStaticDevice.objects.filter(user=request.user).first()
    if not static_device:
        if not get_user_devices(request.user):
            # Direct access to this route without any enrolled device.
            # Reject by redirecting to dashboard, user will be
            # redirected if an OTP is required.
            return HttpResponseRedirect(reverse("dashboard:index"))
        # If user enrolled a device after June 2026, they must have a
        # static device (backup code). If they enrolled before (which
        # is the case for most staff users), they don't have a static
        # device and it's fine.
        if not request.user.is_staff:
            logger.error("User %s has a TOTP device but no backup code", request.user.id)
        context = {"form": LoginWithBackupCodeForm(static_device=None)}
        messages.warning(
            request,
            "Il semble que vous n’ayiez pas de code de récupération. Veuillez contacter le support.",
        )
        return render(request, template_name, context)

    form = LoginWithBackupCodeForm(
        data=request.POST or None,
        static_device=static_device,
    )
    if request.method == "POST" and form.is_valid():
        logger.info("User %s authenticated with 2FA backup code", request.user.id)
        messages.success(
            request,
            "Vous avez été identifié grâce à votre code de récupération. "
            "Vos appareils précedemment enregistrés ont été supprimés. "
            "Vous devez à nouveau enregistrer un appareil.",
        )

        # No need to delete the ItouStaticToken, it's already been
        # done by `ItouStaticDevice.verify_token` (called by the
        # form). However, we need to delete all other TOTP devices,
        # since the user seems to have lost them.
        ItouTOTPDevice.objects.filter(user=request.user).update(disabled_at=timezone.now())
        ItouStaticDevice.objects.filter(user=request.user).delete()

        notify_backup_code_has_been_used(request.user)

        # FIXME (dbaty): shall we also logout the user so that they
        # have to input their password again?

        # Now that the user does not have any usable device anymore,
        # they must enroll again.
        return HttpResponseRedirect(reverse("otp_views:enrollment_step_0_intro"))

    context = {"form": form}
    return render(request, template_name, context)
