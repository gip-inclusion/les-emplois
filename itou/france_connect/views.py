import dataclasses
import datetime
import json
from typing import Optional
from urllib.parse import unquote

import httpx
import sentry_sdk
from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils import crypto, timezone
from django.utils.http import urlencode

from itou.users.models import User
from itou.utils.urls import get_absolute_url

from .models import FranceConnectState


def get_callback_redirect_uri(request):
    redirect_uri = get_absolute_url(reverse("france_connect:callback"))
    next_url = request.GET.get("next")
    if next_url:
        redirect_uri += f"?next={next_url}"

    # The redirect_uri should be defined in the FC settings to be allowed
    return "http://localhost:8080/callback"
    return redirect_uri


def state_new():
    # Generate CSRF and save the state for further verification
    signer = signing.Signer()
    csrf = crypto.get_random_string(length=12)
    csrf_signed = signer.sign(csrf)
    FranceConnectState.objects.create(csrf=csrf)

    return csrf_signed


def state_is_valid(csrf_signed):
    if not csrf_signed:
        return False

    signer = signing.Signer()
    try:
        csrf = signer.unsign(unquote(csrf_signed))
    except signing.BadSignature:
        return False

    france_connect_state = FranceConnectState.objects.filter(csrf=csrf).first()
    if not france_connect_state:
        return False

    # One-time use
    france_connect_state.delete()

    # Cleanup old states if any
    FranceConnectState.objects.cleanup()

    return True


def france_connect_authorize(request):
    redirect_uri = get_callback_redirect_uri(request)
    csrf_signed = state_new()
    data = {
        "response_type": "code",
        "client_id": settings.FRANCE_CONNECT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": settings.FRANCE_CONNECT_SCOPES,
        "state": csrf_signed,
        "nonce": crypto.get_random_string(length=12),
        "acr_values": "eidas1",
    }
    url = settings.FRANCE_CONNECT_URL + settings.FRANCE_CONNECT_ENDPOINT_AUTHORIZE
    return HttpResponseRedirect(f"{url}?{urlencode(data)}")


@dataclasses.dataclass
class FranceConnectUserData:
    username: str
    first_name: str
    last_name: str
    birthdate: datetime.date
    email: str
    phone: str
    address_line_1: str
    post_code: str
    city: str
    country: Optional[str] = None


def load_user_data(user_data):
    user_model_dict = {
        "username": user_data["sub"],
        "first_name": user_data.get("given_name", ""),
        "last_name": user_data.get("family_name", ""),
        "birthdate": datetime.date.fromisoformat(user_data["birthdate"]) if user_data.get("birthdate") else None,
        "email": user_data.get("email"),
        "phone": user_data.get("phone_number"),
        "address_line_1": "",
        "post_code": "",
        "city": "",
        "country": None,
    }

    if "address" in user_data:
        user_model_dict |= {
            "address_line_1": user_data["address"].get("street_address"),
            "post_code": user_data["address"].get("postal_code"),
            "city": user_data["address"].get("locality"),
            "country": user_data["address"].get("country"),
        }

    return user_model_dict


def set_fields_from_user_data(user, fc_user_data):
    # birth_country_id from user_data["birthcountry"]
    # birth_place_id from user_data["birthplace"]
    provider_json = {}
    now = timezone.now()
    provider_info = {"source": "fc", "created_at": now}
    for field in ["username", "first_name", "last_name", "birthdate", "email", "phone"]:
        setattr(user, field, getattr(fc_user_data, field))
        provider_json[field] = provider_info

    if fc_user_data.country == "France":
        for field in ["address_line_1", "post_code", "city"]:
            setattr(user, field, getattr(fc_user_data, field))
            provider_json[field] = provider_info

    user.provider_json = provider_json


def update_fields_from_user_data(user, fc_user_data, provider_json):
    now = timezone.now()

    # Not very smart
    def is_fc_source(field):
        return provider_json.get(field) and provider_json[field]["source"] == "fc"

    def update_time(field):
        provider_json[field]["created_at"] = now

    for field in dataclasses.fields(fc_user_data):
        if field.name == "country":
            continue

        if is_fc_source(field.name):
            setattr(user, field.name, getattr(fc_user_data, field.name))
            update_time(field.name)


def create_or_update_user(fc_user_data: FranceConnectUserData):
    # We can't use a get_or_create here because we have to set provider_json for each field
    try:
        user = User.objects.get(username=fc_user_data.username)
        # Should we update the user fields on user authenticate?
        # In first approach, it safes to update FC fields
        update_fields_from_user_data(user, fc_user_data, user.provider_json)
        created = False
    except User.DoesNotExist:
        # Create a new user
        user = User()
        set_fields_from_user_data(user, fc_user_data)
        created = True
    user.save()

    return user, created


def france_connect_callback(request):  # pylint: disable=too-many-return-statements
    code = request.GET.get("code")
    if code is None:
        return JsonResponse({"message": "La requête ne contient pas le paramètre « code »."}, status=400)

    state = request.GET.get("state")
    if not state_is_valid(state):
        return JsonResponse({"message": "Le paramètre « state » n'est pas valide."}, status=400)

    # redirect_uri = get_callback_redirect_uri(request)
    redirect_uri = "http://localhost:8080/callback"

    data = {
        "client_id": settings.FRANCE_CONNECT_CLIENT_ID,
        "client_secret": settings.FRANCE_CONNECT_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    # Exceptions catched by Sentry
    url = settings.FRANCE_CONNECT_URL + settings.FRANCE_CONNECT_ENDPOINT_TOKEN
    response = httpx.post(url, data=data, timeout=30)

    if response.status_code != 200:
        message = "Impossible d'obtenir le jeton de FranceConnect."
        sentry_sdk.capture_message(f"{message}\n{response.content}")
        # The response is certainly ignored by FC but it's convenient for our tests
        return JsonResponse({"message": message}, status=response.status_code)

    # Contains access_token, token_type, expires_in, id_token
    token_data = response.json()
    print(token_data)

    access_token = token_data.get("access_token")
    if not access_token:
        return JsonResponse({"message": "Aucun champ « access_token » dans la réponse FranceConnect."}, status=400)

    # A token has been provided so it's time to fetch associated user infos
    # because the token is only valid for 5 seconds.
    url = settings.FRANCE_CONNECT_URL + settings.FRANCE_CONNECT_ENDPOINT_USERINFO
    response = httpx.get(
        url,
        params={"schema": "openid"},
        headers={"Authorization": "Bearer " + access_token},
        timeout=60,
    )
    if response.status_code != 200:
        message = "Impossible d'obtenir les informations utilisateur de FranceConnect."
        sentry_sdk.capture_message(message)
        return JsonResponse({"message": message}, status=response.status_code)

    try:
        user_data = json.loads(response.content.decode("utf-8"))
    except json.decoder.JSONDecodeError:
        return JsonResponse(
            {"message": "Impossible de décoder les informations utilisateur."},
            status=400,
        )

    if "sub" not in user_data:
        return JsonResponse(
            {"message": "Le paramètre « sub » n'a pas été retourné par FranceConnect."},
            status=400,
        )

    fc_user_data = FranceConnectUserData(**load_user_data(user_data))
    # Keep token_data["id_token"] to logout from FC
    # At this step, we can update the user's fields in DB and create a session if required
    create_or_update_user(fc_user_data)

    return JsonResponse(user_data)


def france_connect_logout(request):
    if request.user.is_anonymous:
        return JsonResponse({"message": "L'utilisateur n'est pas authentifié."})

    id_token = request.GET.get("id_token")
    if not id_token:
        return JsonResponse({"message": "Le paramètre « id_token » est manquant."}, status=400)

    params = {
        "id_token_hint": id_token,
        "state": "itou",
        "post_logout_redirect_uri": settings.FRANCE_CONNECT_URL_POST_LOGOUT,
    }
    redirect_url = settings.FRANCE_CONNECT_URLS["logout"] + "/?" + urlencode(params)
    return JsonResponse({"url": redirect_url}, status=302)
