from urllib.parse import parse_qsl

import requests
from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error


class PEAMUOAuth2Client(OAuth2Client):
    """
    Required exclusively for injecting realm=/individu
    when requesting access token.
    (╯°□°)╯︵ ┻━┻
    """

    def get_access_token(self, code):
        """
        This whole method is unchanged except for the
        `params = {"realm": "/individu"}` hack.
        Original code:
        https://github.com/pennersr/django-allauth/blob/6a6d3c618ab018234dde8701173093274710ee0a/allauth/socialaccount/providers/oauth2/client.py#L44
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
        # TODO: Proper exception handling
        resp = requests.request(
            self.access_token_method, url, params=params, data=data, headers=self.headers, auth=auth
        )

        access_token = None
        if resp.status_code in [200, 201]:
            # Weibo sends json via 'text/plain;charset=UTF-8'
            if resp.headers["content-type"].split(";")[0] == "application/json" or resp.text[:2] == '{"':
                access_token = resp.json()
            else:
                access_token = dict(parse_qsl(resp.text))
        if not access_token or "access_token" not in access_token:
            raise OAuth2Error("Error retrieving access token: %s" % resp.content)
        return access_token
