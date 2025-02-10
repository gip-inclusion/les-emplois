from django.urls import reverse


def failing_function(*args):
    raise Exception("Something bad")


def test_error_handling(client, mocker):
    some_api_url = reverse("v1:siaes-list")
    mocker.patch("itou.api.siae_api.viewsets.SiaeViewSet.get_queryset", failing_function)

    response = client.get(some_api_url)
    assert response.status_code == 500
    assert response.json() == {"detail": "Something went wrong, sorry. We've been notified."}
