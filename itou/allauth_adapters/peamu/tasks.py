import httpx
from django.conf import settings
from django.utils.http import urlencode
from huey.contrib.djhuey import task


@task()
def huey_logout_from_pe_connect(peamu_id_token, hp_url):
    params = {"id_token_hint": peamu_id_token, "redirect_uri": hp_url}
    peamu_logout_url = f"{settings.PEAMU_AUTH_BASE_URL}/compte/deconnexion?{urlencode(params)}"
    return httpx.get(peamu_logout_url)
