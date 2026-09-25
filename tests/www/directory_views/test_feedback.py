from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from tests.www.directory_views.helpers import get_target_person


def test_contact_feedback_uses_viewer_and_active_organization(client):
    viewer, target, _, person = get_target_person(client)

    response = client.get(reverse("directory:person_detail", kwargs={"key": person.key}))

    organization = response.wsgi_request.current_organization
    assertContains(response, 'src="https://tally.so/widgets/embed.js"')
    assertContains(response, 'data-kind="employeur"')
    assertContains(response, f'data-user-id="{viewer.pk}"')
    assertContains(response, f'data-mail="{viewer.email}"')
    assertContains(response, f'data-org="{organization.display_name}"')
    assertContains(response, f'data-town="{organization.city}"')
    assertNotContains(response, f'data-mail="{target.email}"')
