from django.conf import settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.users.factories import JobSeekerFactory


def test_as_superuser(client):
    admin_user = JobSeekerFactory(is_staff=True, is_superuser=True)
    client.force_login(admin_user)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 200
    assertContains(response, "Affichage des settings")
    response = client.get(reverse("admin:settings_viewer_setting_changelist"))
    assert response.status_code == 200
    assertContains(response, "ALLOWED_HOSTS")
    assertContains(response, "DATABASES")
    assertContains(response, "SECRET_KEY")
    assertNotContains(response, settings.SECRET_KEY)


def test_as_staff(client):
    admin_user = JobSeekerFactory(is_staff=True, is_superuser=False)
    client.force_login(admin_user)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 200
    assertNotContains(response, "Affichage des settings")
    response = client.get(reverse("admin:settings_viewer_setting_changelist"))
    assert response.status_code == 302
