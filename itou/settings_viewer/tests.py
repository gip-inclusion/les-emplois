from django.conf import settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.users.factories import ItouStaffFactory


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
