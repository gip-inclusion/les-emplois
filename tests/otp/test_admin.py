from django.urls import reverse
from pytest_django.asserts import assertNotContains

from tests.otp.factories import ItouTOTPDeviceFactory


def test_admin_details(admin_client):
    key = "8fe0a9983c7dddb4acb0146c5507553371e9f211"
    device = ItouTOTPDeviceFactory(key=key)

    url = reverse("admin:otp_itoutotpdevice_change", args=(device.pk,))
    response = admin_client.get(url)
    assert response.status_code == 200
    assertNotContains(response, key)
