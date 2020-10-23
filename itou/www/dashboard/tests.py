from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from itou.siaes.factories import (
    SiaeAfterGracePeriodFactory,
    SiaeAfterGracePeriodWithMembershipFactory,
    SiaeFactory,
    SiaePendingGracePeriodFactory,
    SiaeWithMembershipFactory,
)
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, SiaeStaffFactory


class DashboardViewTest(TestCase):
    def test_dashboard(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_user_with_inactive_siae_can_still_login_during_grace_period(self):
        siae = SiaePendingGracePeriodFactory()
        user = SiaeStaffFactory()
        siae.members.add(user)
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # User can access basic views.
        url = reverse("siaes_views:configure_jobs")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_user_with_inactive_siae_can_still_login_after_grace_period(self):
        siae = SiaeAfterGracePeriodWithMembershipFactory()
        user = siae.members.get()
        assert siae.has_admin(user)
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # User cannot access basic views.
        url = reverse("siaes_views:configure_jobs")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        # User can still access AF interface to fix its convention.
        url = reverse("siaes_views:show_financial_annexes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class EditUserInfoViewTest(TestCase):
    def test_edit(self):

        user = JobSeekerFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(id=user.id)
        self.assertEqual(user.phone, post_data["phone"])
        self.assertEqual(user.birthdate.strftime("%d/%m/%Y"), post_data["birthdate"])


class SwitchSiaeTest(TestCase):
    def test_switch_siae(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        related_siae = SiaeFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)

        url = reverse("siaes_views:card", kwargs={"siae_id": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)
        self.assertEqual(response.context["siae"], siae)

        url = reverse("dashboard:switch_siae")
        response = self.client.post(url, data={"siae_id": related_siae.pk})
        self.assertEqual(response.status_code, 302)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)

        url = reverse("siaes_views:card", kwargs={"siae_id": related_siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)
        self.assertEqual(response.context["siae"], related_siae)

        url = reverse("siaes_views:configure_jobs")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)

        url = reverse("apply:list_for_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)

    def test_can_still_switch_to_inactive_siae_during_grace_period(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        related_siae = SiaePendingGracePeriodFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)

        url = reverse("dashboard:switch_siae")
        response = self.client.post(url, data={"siae_id": related_siae.pk})
        self.assertEqual(response.status_code, 302)

        # User has indeed switched.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)

    def test_can_still_switch_to_inactive_siae_after_grace_period(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        related_siae = SiaeAfterGracePeriodFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)

        url = reverse("dashboard:switch_siae")
        response = self.client.post(url, data={"siae_id": related_siae.pk})
        self.assertEqual(response.status_code, 302)

        # User has indeed switched.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], related_siae)
