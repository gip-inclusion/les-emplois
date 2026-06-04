import base64
import binascii

import segno
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice, default_key as generate_otp_key

from itou.otp.utils import create_otp_backup_code, get_user_devices
from itou.utils.auth import check_user
from itou.utils.readonly import http_methods
from itou.www.otp_views.enums import DeviceType
from itou.www.otp_views.forms import ConfirmTOTPDeviceForm


check_user_for_otp = check_user(lambda user: user.is_staff)


@http_methods(db_readonly=["GET", "HEAD"], db_write=["POST"])
@check_user_for_otp
def otp_devices(request, template_name="otp_views/otp_devices.html"):
    devices = get_user_devices(request.user)
    if request.method == "POST":
        if device_id := request.POST.get("delete-device"):
            device = get_object_or_404(TOTPDevice.objects.filter(user=request.user), pk=device_id)
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

    unsaved_device = TOTPDevice(
        user=request.user,
        key=binascii.hexlify(base64.b32decode(request.POST["key"].encode())).decode()
        if request.POST
        else generate_otp_key(),
    )
    # Disable `throttle_increment()`, which is called when failing to
    # verify a token (via our form validation) and saves the instance
    # (which we don't want). The instance will be saved below only if
    # the form is valid.
    unsaved_device.throttle_increment = lambda *args, **kwargs: 1

    backup_code = None
    post_save_url = None
    form = ConfirmTOTPDeviceForm(
        data=request.POST or None,
        device_type=device_type,
        device=unsaved_device,
    )
    if request.method == "POST" and form.is_valid():
        unsaved_device.name = form.cleaned_data["name"]
        unsaved_device.save()
        device = unsaved_device
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
        "qrcode": segno.make(unsaved_device.config_url).svg_data_uri(),
        "backup_code": backup_code,
        "post_save_url": post_save_url,
    }
    return render(request, template_name, context)
