from django.conf import settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from tests.users.factories import ItouStaffFactory


APP_VERBOSE_NAME = "Affichage des settings"


def test_as_superuser(client):
    admin_user = ItouStaffFactory(is_superuser=True)
    client.force_login(admin_user)
    response = client.get(reverse("admin:index"))
    assertContains(response, APP_VERBOSE_NAME)
    response = client.get(reverse("admin:settings_viewer_setting_changelist"))
    assertContains(response, "ALLOWED_HOSTS")
    assertContains(response, "DATABASES")
    assertContains(response, "SECRET_KEY")
    assertNotContains(response, settings.SECRET_KEY)


def test_as_staff(client):
    admin_user = ItouStaffFactory(is_superuser=False)
    client.force_login(admin_user)
    response = client.get(reverse("admin:index"))
    assertNotContains(response, APP_VERBOSE_NAME)
    response = client.get(reverse("admin:settings_viewer_setting_changelist"))
    assert response.status_code == 302
