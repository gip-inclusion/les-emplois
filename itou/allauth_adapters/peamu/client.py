from urllib.parse import parse_qsl

import requests
from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error
from django.conf import settings


class PEAMUOAuth2Client(OAuth2Client):
    """
    Required exclusively for injecting realm=/individu
    when requesting access token.
    (╯°□°)╯︵ ┻━┻
    """

    def get_access_token(self, code, pkce_code_verifier=None):
        """
        This whole method is unchanged except for the
        `params = {"realm": "/individu"}` hack.
        Original code:
        https://github.com/pennersr/django-allauth/blob/c1b8fe5eef94761ad349048737c5b036e719a501/allauth/socialaccount/providers/oauth2/client.py#L48
        """
        data = {"redirect_uri": self.callback_url, "grant_type": "authorization_code", "code": code}
        if self.basic_auth:
            auth = requests.auth.HTTPBasicAuth(self.consumer_key, self.consumer_secret)
        else:
            auth = None
            data.update({"client_id": self.consumer_key, "client_secret": self.consumer_secret})
        params = {"realm": "/individu"}
        self._strip_empty_keys(data)
        url = self.access_token_url
        if self.access_token_method == "GET":
            params = data
            data = None
        if data and pkce_code_verifier:
            data["code_verifier"] = pkce_code_verifier
        resp = requests.request(
            self.access_token_method,
            url,
            params=params,
            data=data,
            headers=self.headers,
            auth=auth,
            timeout=settings.REQUESTS_TIMEOUT,
        )

        access_token = None
        if resp.status_code in [200, 201]:
            # Weibo sends json via 'text/plain;charset=UTF-8'
            if resp.headers["content-type"].split(";")[0] == "application/json" or resp.text[:2] == '{"':
                access_token = resp.json()
            else:
                access_token = dict(parse_qsl(resp.text))
        if not access_token or "access_token" not in access_token:
            raise OAuth2Error(f"Error retrieving access token: {resp.content}")
        return access_token
