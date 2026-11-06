import datetime

from django.urls import reverse
from pytest_django.asserts import assertContains, assertHTMLEqual

from itou.asp.models import Commune
from tests.utils.testing import parse_response_to_soup


def test_access_to_ignored_communes(admin_client):
    ignored = Commune.objects.create(name="CILAOS", code="97824", start_date=datetime.date(1900, 1, 1), ignore=True)
    response = admin_client.get(reverse("admin:asp_commune_change", args=(ignored.pk,)))
    assertContains(response, ignored.name)

    # use parse_response_to_soup to avoid issue with static img URL in CI
    soup = parse_response_to_soup(response, ".field-ignore")
    assertHTMLEqual(
        str(soup),
        """\
        <div class="field-ignore form-row">
          <div>
            <div class="flex-container">
              <label>Commune désactivée :</label>
              <div class="readonly"><img src="/static/admin/img/icon-yes.svg" alt="True"></div>
            </div>
          </div>
        </div>""",
    )
