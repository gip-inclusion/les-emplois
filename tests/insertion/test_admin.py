from django.contrib.auth.models import Permission
from django.contrib.gis.geos import Point
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.insertion.models import OrientationProcessLink
from tests.cities.factories import create_city_vannes
from tests.insertion.factories import OrientationFactory, OrientationProcessLinkFactory, StructureFactory
from tests.users.factories import ItouStaffFactory


class TestOrientationProcessLink:
    def test_create_orientation_process_link_button(self, client):
        orientation = OrientationFactory()
        create_link_url = reverse(
            "admin:insertion_create_orientation_process_link", kwargs={"orientation_id": orientation.pk}
        )

        # Basic staff users don’t have access to the button
        admin_user = ItouStaffFactory()
        orientation_perm = Permission.objects.get(codename="view_orientation")
        admin_user.user_permissions.add(orientation_perm)
        client.force_login(admin_user)
        response = client.get(reverse("admin:insertion_orientation_change", kwargs={"object_id": orientation.pk}))
        assertNotContains(response, create_link_url)

        # Users with the correct permission can
        link_perm = Permission.objects.get(codename="add_orientationprocesslink")
        admin_user.user_permissions.add(link_perm)
        response = client.get(reverse("admin:insertion_orientation_change", kwargs={"object_id": orientation.pk}))
        assertContains(response, create_link_url)

    def test_create_orientation_process_link(self, client):
        orientation = OrientationFactory()

        # Basic staff users cannot post to create a new link
        admin_user = ItouStaffFactory()
        orientation_perm = Permission.objects.get(codename="view_orientation")
        admin_user.user_permissions.add(orientation_perm)
        client.force_login(admin_user)
        response = client.post(reverse("admin:insertion_orientation_change", kwargs={"object_id": orientation.pk}))
        assert response.status_code == 403

        # Users with the correct permission can
        link_perm = Permission.objects.get(codename="add_orientationprocesslink")
        admin_user.user_permissions.add(link_perm)
        response = client.post(
            reverse("admin:insertion_create_orientation_process_link", kwargs={"orientation_id": orientation.pk})
        )
        assert response.status_code == 302
        assert OrientationProcessLink.objects.exists()

    def test_delete_orientation_process_link(self, client):
        process_link = OrientationProcessLinkFactory()

        # Basic staff users cannot delete a link
        admin_user = ItouStaffFactory()
        orientation_perms = Permission.objects.filter(
            codename__in=["view_orientation", "change_orientation", "view_orientationprocesslink"]
        )
        admin_user.user_permissions.add(*orientation_perms)
        client.force_login(admin_user)
        data = {
            "process_links-TOTAL_FORMS": "1",
            "process_links-INITIAL_FORMS": "1",
            "process_links-MIN_NUM_FORMS": "0",
            "process_links-MAX_NUM_FORMS": "1",
            "process_links-0-id": str(process_link.pk),
            "process_links-0-orientation": str(process_link.orientation.pk),
            "process_links-0-DELETE": "on",
            "_save": "Enregistrer",
        }
        response = client.post(
            reverse("admin:insertion_orientation_change", kwargs={"object_id": process_link.orientation.pk}), data=data
        )
        assert response.status_code == 302
        assert OrientationProcessLink.objects.exists()

        # Users with the correct permission can
        link_perm = Permission.objects.get(codename="delete_orientationprocesslink")
        admin_user.user_permissions.add(link_perm)
        response = client.post(
            reverse("admin:insertion_orientation_change", kwargs={"object_id": process_link.orientation.pk}), data=data
        )
        assert response.status_code == 302
        assert not OrientationProcessLink.objects.exists()


def test_structure_admin_shows_geolocation(admin_client):
    vannes = create_city_vannes()
    structure = StructureFactory(
        insee_city=vannes,
        coordinates=Point(2.35511, 48.869364, srid=4326),
    )

    response = admin_client.get(reverse("admin:insertion_structure_change", args=(structure.pk,)))

    assertContains(
        response,
        f"""
        <div class="form-row field-insee_city">
            <div>
                <div class="flex-container">
                    <label>Insee city&nbsp;:</label>
                    <div class="readonly">
                        <a href="/admin/cities/city/{vannes.pk}/change/">Vannes (56)</a>
                    </div>
                </div>
            </div>
        </div>
        """,
        html=True,
        count=1,
    )
    assertContains(
        response,
        """
        <div class="flex-container">
            <label>Coordinates&nbsp;:</label>
            <div class="readonly">SRID=4326;POINT (2.35511 48.869364)</div>
        </div>
        """,
        html=True,
        count=1,
    )
