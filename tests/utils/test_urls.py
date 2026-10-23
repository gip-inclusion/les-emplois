import inspect

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import URLResolver

from config import urls as root_urls
from itou.utils.urls import get_zendesk_form_url
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    ProfessionalFactory,
)
from tests.utils.testing import get_request, reload_module


class TestZendeskUrl:
    def test_anonymous_user(self, snapshot):
        request = get_request(AnonymousUser())
        assert get_zendesk_form_url(request) == snapshot

    def test_job_seeker(self, snapshot):
        request = get_request(JobSeekerFactory(for_snapshot=True))
        assert get_zendesk_form_url(request) == snapshot

    def test_labor_inspector(self, snapshot):
        request = get_request(
            LaborInspectorFactory(
                for_snapshot=True,
                membership__institution__name="Ministère des affaires étranges",
            )
        )
        assert get_zendesk_form_url(request) == snapshot

    def test_employer(self, snapshot):
        request = get_request(
            EmployerFactory(
                for_snapshot=True,
                membership__company__for_snapshot=True,
            )
        )
        assert get_zendesk_form_url(request) == snapshot

        # fallback on company phone
        request.user.phone = None
        assert get_zendesk_form_url(request) == snapshot(name="company_phone")

    def test_prescriber(self, snapshot):
        request = get_request(
            PrescriberFactory(
                for_snapshot=True,
                membership__organization__for_snapshot=True,
                membership__organization__phone="0123456789",
            )
        )
        assert get_zendesk_form_url(request) == snapshot(name="prescriber phone")

        # fallback on organization phone
        request.user.phone = None
        assert get_zendesk_form_url(request) == snapshot(name="organization phone")

    def test_pro_no_organization(self, snapshot):
        request = get_request(ProfessionalFactory(for_snapshot=True))
        assert get_zendesk_form_url(request) == snapshot


def iter_url_modules(urlpatterns):
    """Yield the URLconf modules included, directly or not, by ``urlpatterns``."""
    for pattern in urlpatterns:
        if isinstance(pattern, URLResolver):
            if inspect.ismodule(pattern.urlconf_module):
                yield pattern.urlconf_module
            yield from iter_url_modules(pattern.url_patterns)


@pytest.mark.parametrize(
    "module",
    sorted(
        (
            module
            for module in {root_urls, *iter_url_modules(root_urls.urlpatterns)}
            # Only check our own URLconfs: third-party ones (allauth, rest_framework) are not ours to fix
            if module.__name__.startswith(("config.", "itou."))
        ),
        key=lambda module: module.__name__,
    ),
    ids=lambda module: module.__name__,
)
def test_urlconf_can_be_reexecuted(module):
    """Any URLconf of the tree that failed to import is executed again on the next access.

    None of them may have non-idempotent import-time side effects: registering a converter twice, for instance,
    raises a ValueError hiding the original error.
    """
    with reload_module(module):
        pass
