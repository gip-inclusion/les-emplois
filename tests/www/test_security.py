import datetime
import re

from django.urls import reverse


def test_security_txt_is_valid(client):
    response = client.get(reverse("security-txt"))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain; charset=utf-8"

    expire_re = re.compile(r"^Expires: (?P<expires>.*)$")
    for line in response.content.decode().splitlines():
        if match := expire_re.match(line):
            expiry = match.group("expires")
            expiry = datetime.datetime.fromisoformat(expiry)
            break

    assert expiry - datetime.datetime.now(tz=datetime.UTC) >= datetime.timedelta(days=14)
