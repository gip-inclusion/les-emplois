from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory


class EditUserInfoViewTest(TestCase):
    def test_edit(self):

        user = JobSeekerFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"birthdate": "20/12/1978", "phone": "0610203050"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(id=user.id)
        self.assertEqual(user.phone, post_data["phone"])
        self.assertEqual(user.birthdate.strftime("%d/%m/%Y"), post_data["birthdate"])
