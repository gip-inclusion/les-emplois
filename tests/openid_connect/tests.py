import pytest
from django.conf import settings
from django.urls import reverse


@pytest.mark.parametrize("idp", ["france_connect", "pro_connect", "ft_connect"])
def test_callback_sets_browser_id(client, idp):
    """It is nice to have a browser_id in the LOG_IN event of the audit_trail,
    so ensure the browser_id cookie is created for this query.

    Even though an openid connect callback is a GET request.
    """

    url = reverse(f"{idp}:callback")
    response = client.get(url)
    assert response.cookies[settings.BROWSER_ID_COOKIE_NAME]
