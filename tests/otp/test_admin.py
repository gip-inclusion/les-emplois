from django.urls import reverse
from pytest_django.asserts import assertNotContains

from itou.otp.enums import ResetRequestState
from tests.otp.factories import ItouTOTPDeviceFactory, ResetRequestFactory
from tests.utils.testing import parse_response_to_soup


def test_admin_details(admin_client):
    key = "8fe0a9983c7dddb4acb0146c5507553371e9f211"
    device = ItouTOTPDeviceFactory(key=key)

    url = reverse("admin:otp_itoutotpdevice_change", args=(device.pk,))
    response = admin_client.get(url)
    assert response.status_code == 200
    assertNotContains(response, key)


def test_admin_2fa_reset_has_accept_and_refuse_buttons(admin_client):
    reset_request = ResetRequestFactory()
    url = reverse("admin:otp_resetrequest_change", args=(reset_request.pk,))
    response = admin_client.get(url)
    html = parse_response_to_soup(response, selector="#otp-reset-request-transitions")
    assert html.find("input", {"value": "Accepter"})
    assert html.find("input", {"value": "Refuser"})


def test_accept_2fa_reset_accept(admin_client):
    reset_request = ResetRequestFactory()
    url = reverse("admin:otp_resetrequest_change", args=(reset_request.pk,))
    assert reset_request.state == ResetRequestState.PENDING
    admin_client.post(
        url,
        data={
            "transition_accept": 1,
            "logs-TOTAL_FORMS": "0",
            "logs-INITIAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
        },
    )
    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.ACCEPTED


def test_accept_2fa_reset_deny(admin_client):
    reset_request = ResetRequestFactory()
    url = reverse("admin:otp_resetrequest_change", args=(reset_request.pk,))
    assert reset_request.state == ResetRequestState.PENDING
    admin_client.post(
        url,
        data={
            "transition_deny": 1,
            "logs-TOTAL_FORMS": "0",
            "logs-INITIAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
        },
    )
    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.DENIED
