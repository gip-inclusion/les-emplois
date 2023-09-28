import pytest
from django.conf import settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from tests.users.factories import ItouStaffFactory


pytestmark = pytest.mark.ignore_template_errors


@pytest.mark.filterwarnings(
    "ignore:"
    "The DEFAULT_FILE_STORAGE setting is deprecated. Use STORAGES instead.:"
    "django.utils.deprecation.RemovedInDjango51Warning",
    "ignore:"
    "The STATICFILES_STORAGE setting is deprecated. Use STORAGES instead.:"
    "django.utils.deprecation.RemovedInDjango51Warning",
    "ignore:"
    "The USE_L10N setting is deprecated. "
    "Starting with Django 5.0, localized formatting of data will always be enabled. "
    "For example Django will display numbers and dates using the format of the current locale.:"
    "django.utils.deprecation.RemovedInDjango50Warning",
)
def test_as_superuser(client):
    admin_user = ItouStaffFactory(is_superuser=True)
    client.force_login(admin_user)
    response = client.get(reverse("admin:index"))
    assertContains(response, "Affichage des settings")
    response = client.get(reverse("admin:settings_viewer_setting_changelist"))
    assertContains(response, "ALLOWED_HOSTS")
    assertContains(response, "DATABASES")
    assertContains(response, "SECRET_KEY")
    assertNotContains(response, settings.SECRET_KEY)


def test_as_staff(client):
    admin_user = ItouStaffFactory(is_superuser=False)
    client.force_login(admin_user)
    response = client.get(reverse("admin:index"))
    assertNotContains(response, "Affichage des settings")
    response = client.get(reverse("admin:settings_viewer_setting_changelist"))
    assert response.status_code == 302
