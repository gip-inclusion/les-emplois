import base64
import binascii
import logging

import segno
import xworkflows
from django import forms
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import default_key as generate_otp_key

from itou.common_apps.organizations.utils import get_org_admins
from itou.otp.emails import notify_2fa_reset_request_init, notify_backup_code_has_been_used
from itou.otp.enums import ResetRequestState
from itou.otp.models import Itou2FAResetRequest, ItouStaticDevice, ItouTOTPDevice
from itou.otp.utils import (
    create_otp_backup_code,
    get_user_devices,
    user_can_enroll_otp_device,
    user_can_manage_otp_devices,
)
from itou.utils.auth import check_user_or_404
from itou.utils.readonly import http_methods
from itou.utils.urls import get_safe_url
from itou.www.otp_views.enums import DeviceType
from itou.www.otp_views.forms import ConfirmTOTPDeviceForm, LoginWithBackupCodeForm, VerifyOTPForm


logger = logging.getLogger(__name__)

check_user_can_enroll = check_user_or_404(user_can_enroll_otp_device)
check_user_can_manage_devices = check_user_or_404(user_can_manage_otp_devices)


@http_methods(db_readonly=["GET", "HEAD"], db_write=["POST"])
@check_user_can_manage_devices
def otp_devices(request, template_name="otp_views/otp_devices.html"):
    devices = get_user_devices(request.user)
    if request.method == "POST":
        if device_id := request.POST.get("delete-device"):
            device = get_object_or_404(
                ItouTOTPDevice.objects.filter(user=request.user, disabled_at=None), pk=device_id
            )
            if device != request.user.otp_device:
                messages.success(request, "L’appareil a été supprimé.")
                # Soft delete for auditing purposes (see the command `purge_disabled_otp_devices`)
                device.disabled_at = timezone.now()
                device.save(update_fields=["disabled_at"])
                devices = get_user_devices(request.user)
            else:
                messages.error(request, "Impossible de supprimer l’appareil qui a été utilisé pour se connecter.")

    context = {"devices": devices}
    return render(request, template_name, context)


def reset_request_self_cancel(request, template_name="otp_views/reset_request_self_cancel.html"):
    form = forms.Form(data={})
    context = {"form": form, "denied": False}
    try:
        context["reset_request"] = reset_request = Itou2FAResetRequest.objects.get(
            user=request.user, state__in=(ResetRequestState.PENDING, ResetRequestState.ACCEPTED)
        )
    except Itou2FAResetRequest.DoesNotExist:
        context["reset_request"] = reset_request = None
    if request.method == "POST" and reset_request:
        reset_request.deny(actor=request.user, msg=f"Using {request.path}")
        return HttpResponseRedirect(reverse("otp_views:reset_request_self_cancelled"))
    return render(request, template_name, context=context)


def reset_request_init(request, template_name="otp_views/reset_request_init.html"):
    form = forms.Form(data={})
    admins = get_org_admins(getattr(request, "organizations", None), request.user)
    context = {"form": form, "admins": admins, "disabled": False}
    if not get_user_devices(request.user):
        messages.warning(request, "Aucune double authentification n’est configurée pour votre compte.")
        context["disabled"] = True
        return render(request, template_name, context)

    if request.user.is_verified():
        messages.warning(
            request,
            "Vous êtes correctement authentifié avec votre second facteur.",
        )
        context["disabled"] = True
        return render(request, template_name, context)

    if Itou2FAResetRequest.objects.filter(
        user=request.user, state__in=(ResetRequestState.PENDING, ResetRequestState.ACCEPTED)
    ):
        messages.warning(request, "Une demande de réinitialisation est déjà en cours pour votre compte.")
        context["disabled"] = True
        return render(request, template_name, context)

    if request.method == "POST":
        Itou2FAResetRequest.objects.create(user=request.user)
        notify_2fa_reset_request_init(request.user, getattr(request, "organizations", None))
        return HttpResponseRedirect(reverse("otp_views:reset_request_created"))

    return render(request, template_name, context)


def reset_request_created(request, template_name="otp_views/reset_request_created.html"):
    return render(
        request,
        template_name,
        context={"org_has_admins": bool(get_org_admins(getattr(request, "organizations", None), request.user))},
    )


def reset_request_do_reset(request, nonce, template_name="otp_views/reset_request_do_reset.html"):
    reset_request = get_object_or_404(Itou2FAResetRequest.objects.select_for_update(of=("self",)), nonce=nonce)
    if reset_request.user != request.user:
        logger.warning("User %s tried to use 2fa reset link of %s", request.user, reset_request.user)
        return render(request, template_name, {"success": False})
    context = {}
    try:
        context["success"] = reset_request.reset_devices(actor=request.user)
        status = 200
    except xworkflows.base.InvalidTransitionError:
        context["success"] = False
        status = 400
    return render(request, template_name, context, status=status)


@check_user_can_enroll
def enrollment_step_0_intro(request, template_name="otp_views/enrollment_step_0_intro.html"):
    after_recovery = "after_recovery" in request.GET
    if after_recovery:
        disabled_devices = ItouTOTPDevice.objects.filter(user=request.user, disabled_at__isnull=False)
    else:
        disabled_devices = ()  # ignored by template
    context = {
        "after_recovery": after_recovery,
        "disabled_devices": disabled_devices,
        "next_step_url": reverse("otp_views:enrollment_step_1_choose_device_type"),
    }
    return render(request, template_name, context)


@check_user_can_enroll
def enrollment_step_1_choose_device_type(request, template_name="otp_views/enrollment_step_1_choose_device_type.html"):
    context = {"next_step_url": reverse("otp_views:enrollment_step_2_and_3_confirm_device")}
    return render(request, template_name, context)


@http_methods(db_readonly=["GET", "HEAD"], db_write=["POST"])
@check_user_can_enroll
def enrollment_step_2_and_3_confirm_device(
    request, template_name="otp_views/enrollment_step_2_and_3_confirm_device.html"
):
    previous_step_url = reverse("otp_views:enrollment_step_1_choose_device_type")
    device_type = request.GET.get("device_type") or request.POST.get("device_type")
    if device_type not in DeviceType:
        # should not happen, unless user manipulates the request
        return HttpResponseRedirect(previous_step_url)

    if request.POST:
        if not request.POST.get("key"):
            return HttpResponseRedirect(previous_step_url)
        try:
            key = binascii.hexlify(base64.b32decode(request.POST["key"].encode())).decode()
        except (KeyError, binascii.Error):
            return HttpResponseRedirect(previous_step_url)
    else:
        key = generate_otp_key()

    device = ItouTOTPDevice(user=request.user, key=key)

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


@method_decorator(check_user_can_manage_devices, name="dispatch")
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
        Itou2FAResetRequest.objects.filter(
            user=self.request.user, state__in=(ResetRequestState.PENDING, ResetRequestState.ACCEPTED)
        ).deny(
            actor=self.request.user, msg="User successfully logged with its current 2FA"
        )  # Invalidate all 2FA reset requests as the user finally have it.
        return super().form_valid(form)

    def get_success_url(self):
        return get_safe_url(self.request, REDIRECT_FIELD_NAME, reverse("dashboard:index"))


@check_user_can_manage_devices
def login_with_backup_code(request, template_name="otp_views/login_with_backup_code.html"):
    static_device = ItouStaticDevice.objects.filter(user=request.user).first()
    if not static_device:
        # If user enrolled a device after June 2026, they must have a
        # static device (backup code). If they enrolled before (which
        # is the case for most staff users), they don't have a static
        # device and it's fine.
        if not request.user.is_staff:
            logger.error("User %s has a TOTP device but no backup code", request.user.id)
        context = {"form": LoginWithBackupCodeForm(static_device=None)}
        messages.warning(
            request,
            "Il semble que vous n’ayez pas de code de récupération. Veuillez contacter le support.",
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
            "Code de récupération validé. Votre identité a été vérifiée. "
            "Vous pouvez maintenant reconfigurer votre double authentification",
            extra_tags="toast",
        )

        # No need to delete the ItouStaticToken, it's already been
        # done by `ItouStaticDevice.verify_token` (called by the
        # form). However, we need to delete all other TOTP devices,
        # since the user seems to have lost them.
        ItouTOTPDevice.objects.filter(user=request.user, disabled_at=None).update(disabled_at=timezone.now())
        ItouStaticDevice.objects.filter(user=request.user).delete()

        notify_backup_code_has_been_used(request.user)

        # FIXME (dbaty): shall we also logout the user so that they
        # have to input their password again?

        # Now that the user does not have any usable device anymore,
        # they must enroll again.
        return HttpResponseRedirect(
            reverse(
                "otp_views:enrollment_step_0_intro",
                query={
                    "after_recovery": "1",
                },
            )
        )

    context = {"form": form}
    return render(request, template_name, context)
