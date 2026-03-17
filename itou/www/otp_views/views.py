from base64 import b32encode

import segno
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django_otp import devices_for_user, login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.utils.auth import check_user
from itou.www.otp_views.forms import ConfirmTOTPDeviceForm


@check_user(lambda user: user.is_authenticated)
def otp_devices(request, template_name="otp_views/otp_devices.html"):
    if request.method == "POST":
        if request.POST.get("action") == "new":
            device, _ = TOTPDevice.objects.get_or_create(user=request.user, confirmed=False)
            return HttpResponseRedirect(reverse("otp_views:otp_confirm_device", kwargs={"device_id": device.pk}))
        if device_id := request.POST.get("delete-device"):
            device = get_object_or_404(TOTPDevice.objects.filter(user=request.user), pk=device_id)
            if device != request.user.otp_device:
                messages.success(request, "L’appareil a été supprimé.")
                device.delete()
            else:
                messages.error(request, "Impossible de supprimer l’appareil qui a été utilisé pour se connecter.")

    context = {"devices": sorted(devices_for_user(request.user), key=lambda device: device.created_at)}
    return render(request, template_name, context)


@check_user(lambda user: user.is_authenticated)
def otp_confirm_device(request, device_id, template_name="otp_views/otp_confirm_device.html"):
    device = get_object_or_404(TOTPDevice.objects.filter(user=request.user, confirmed=False), pk=device_id)

    form = ConfirmTOTPDeviceForm(data=request.POST or None, device=device)
    if request.method == "POST" and form.is_valid():
        device.confirmed = True
        device.name = form.cleaned_data["name"]
        device.save(update_fields=["name", "confirmed"])
        messages.success(request, "Votre nouvel appareil est confirmé", extra_tags="toast")
        # Mark the user as verified
        otp_login(request, device)
        return HttpResponseRedirect(reverse("otp_views:otp_devices"))

    context = {
        "form": form,
        "otp_secret": b32encode(device.bin_key).decode(),
        # Generate svg data uri qrcode
        "qrcode": segno.make(device.config_url).svg_data_uri(),
        "otp_verified": False,
    }
    return render(request, template_name, context)
