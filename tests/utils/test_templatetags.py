from datetime import UTC, date, datetime
from urllib.parse import urlsplit

import pytest
from django import forms
from django.contrib.auth import authenticate, get_user
from django.contrib.messages import SUCCESS
from django.contrib.messages.storage.base import Message
from django.core.management import call_command
from django.http import QueryDict
from django.template import Context, Template
from django.test import override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse as django_reverse
from django.utils.safestring import mark_safe
from freezegun import freeze_time
from pytest_django.asserts import assertHTMLEqual

from itou.insertion.models import GenericReferenceItemKind
from itou.job_applications.enums import JobApplicationState
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.templatetags.badges import criterion_certification_badge
from itou.utils.templatetags.demo_accounts import (
    employers_accounts_tag,
    job_seekers_accounts_tag,
    prescribers_accounts_tag,
)
from itou.utils.templatetags.dora import dora_orientation_url
from itou.utils.templatetags.nav import NAV_ENTRIES
from itou.utils.templatetags.str_filters import urlize_new_tab
from itou.utils.types import InclusiveDateRange
from tests.eligibility.factories import IAESelectedAdministrativeCriteriaFactory
from tests.insertion.factories import GenericReferenceItemFactory, ServiceFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.testing import pretty_indented
from tests.www.eligibility_views.utils import (
    CERTIFICATION_ERROR_BADGE_HTML,
    CERTIFIED_BADGE_HTML,
    EXPIRED_CERTIFICATION_HTML,
    IN_PROGRESS_BADGE_HTML,
    NOT_CERTIFIED_BADGE_HTML,
    certified_in_the_future_html,
    certified_temporarily_html,
)


def test_matomo_event(snapshot):
    template = Template('{% load matomo %}<a href="#" {% matomo_event "category" "action" "option" %} >')
    assert pretty_indented(template.render(Context({}))) == snapshot


class TestButtonsForm:
    def test_itou_buttons_form(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form %}")
        assert pretty_indented(template.render(Context({}))) == snapshot(name="no params")

    def test_itou_buttons_form_reset_url(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form %}")
        assert pretty_indented(template.render(Context({}))) == snapshot(name="default_reset_url")

        template = Template('{% load buttons_form %}{% itou_buttons_form reset_url="/reset" %}')
        assert pretty_indented(template.render(Context({}))) == snapshot(name="reset_url")

    def test_itou_buttons_with_primary_name_and_value(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form primary_name="name" primary_value="1" %}')
        assert pretty_indented(template.render(Context({}))) == snapshot(name="with_primary_name_and_value")

    def test_itou_buttons_with_primary_aria_label(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form primary_aria_label="label" %}')
        assert pretty_indented(template.render(Context({}))) == snapshot(name="with_primary_aria_label")

    def test_itou_buttons_with_primary_url(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form primary_url="/next" %}')
        assert pretty_indented(template.render(Context({}))) == snapshot(name="with_primary_url")

    def test_itou_buttons_with_primary_name_value_aria_label_and_matomo_tags(self, snapshot):
        template = Template(
            "{% load buttons_form %}"
            '{% itou_buttons_form primary_name="name" primary_value="1" '
            'primary_aria_label="label" '
            'matomo_category="category" matomo_action="action" matomo_name="name" %}'
        )
        assert pretty_indented(template.render(Context({}))) == snapshot(
            name="with_primary_name_value_aria_label_and_matomo_tags"
        )

    def test_itou_buttons_with_primary_disabled(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form primary_disabled=True %}")
        assert pretty_indented(template.render(Context({}))) == snapshot(name="with_primary_disabled")

    def test_itou_buttons_with_secondary_aria_label(self, snapshot):
        template = Template(
            '{% load buttons_form %}{% itou_buttons_form secondary_url="/prev" secondary_aria_label="label" %}'
        )
        assert pretty_indented(template.render(Context({}))) == snapshot(name="with_secondary_aria_label")

    def test_itou_buttons_with_secondary_url(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form secondary_url="/do" %}')
        assert pretty_indented(template.render(Context({}))) == snapshot(name="no_form_title")

    def test_itou_buttons_with_secondary_name_and_value(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form secondary_name="name" secondary_value="1" %}')
        assert pretty_indented(template.render(Context({}))) == snapshot(name="with_secondary_name_and_value")

    def test_itou_buttons_with_secondary_name_and_value_without_reset_url(self, snapshot):
        template = Template(
            '{% load buttons_form %}{% itou_buttons_form secondary_name="name" secondary_value="1" reset_url=None %}'
        )
        assert pretty_indented(template.render(Context({}))) == snapshot(
            name="with_secondary_name_and_value_without_reset_url"
        )

    def test_itou_buttons_matomo_event(self, snapshot):
        template = Template(
            "{% load buttons_form %}"
            '{% itou_buttons_form matomo_category="category" matomo_action="action" matomo_name="name" %}'
        )
        assert pretty_indented(template.render(Context({}))) == snapshot(name="matomo_event")

    def test_itou_buttons_mandatory_fields_mention(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form show_mandatory_fields_mention=False %}")
        assert pretty_indented(template.render(Context({}))) == snapshot(name="no_mandatory_fields_mention")


class TestNav:
    @pytest.fixture(scope="class")
    @classmethod
    def named_urls(cls):
        resolver = get_resolver()
        known_urls = set()
        for resolver in resolver.url_patterns:
            if isinstance(resolver, URLResolver):
                prefix = f"{resolver.namespace}:" if resolver.namespace else ""
                for urlname in resolver.reverse_dict:
                    if isinstance(urlname, str):
                        qualname = f"{prefix}{urlname}"
                        known_urls.add(qualname)
            elif isinstance(resolver, URLPattern):
                if resolver.name:
                    known_urls.add(resolver.name)
            else:
                raise ValueError
        return frozenset(known_urls)

    def test_active_view_names(self, named_urls):
        # build all valid view names
        for entry in NAV_ENTRIES.values():
            for view_name in entry.active_view_names:
                assert view_name in named_urls


class TestThemeInclusion:
    def test_collapse_field(self, snapshot):
        class NIRForm(forms.Form):
            no_nir = forms.BooleanField(required=False)  # Prevent error when unchecked
            nir = forms.CharField()

        template = Template('{% load theme_inclusion %}{% collapse_field form.no_nir target_id="nir" %}')
        assert template.render(Context({"form": NIRForm()})) == snapshot(name="unchecked")
        assert template.render(Context({"form": NIRForm(data={"no_nir": False})})) == snapshot(name="bound unchecked")
        assert template.render(Context({"form": NIRForm(data={"no_nir": True})})) == snapshot(name="bound checked")

    def test_collapse_field_multiple_controls(self):
        class NIRForm(forms.Form):
            no_nir = forms.BooleanField()
            nir = forms.CharField()

        field_markup = '{% collapse_field form.no_nir target_id="nir" %}'
        template = Template("{% load theme_inclusion %}" + field_markup * 2)
        with pytest.raises(NotImplementedError):
            template.render(Context({"form": NIRForm()}))

    def test_itou_toast_content(self):
        TOAST_TITLE = "title"
        TOAST_CONTENT = "<b>content</b>"
        MESSAGE = f"{TOAST_TITLE}||{TOAST_CONTENT}"
        UNSAFE_MESSAGE = Message(message=MESSAGE, level=SUCCESS)
        SAFE_MESSAGE = Message(message=mark_safe(MESSAGE), level=SUCCESS)
        template = Template(
            "{% load theme_inclusion %}<b>{{message|itou_toast_title}}</b><p>{{message|itou_toast_content}}</p>"
        )
        assert template.render(Context({"message": UNSAFE_MESSAGE})) == "<b>title</b><p>&lt;b&gt;content&lt;/b&gt;</p>"
        assert template.render(Context({"message": SAFE_MESSAGE})) == "<b>title</b><p><b>content</b></p>"


@pytest.fixture
def load_test_users():
    call_command("loaddata", "users__user.json")
    call_command("loaddata", "account__email_address.json")


class TestDemoAccount:
    @pytest.mark.parametrize(
        "user_kind,template_tag",
        [
            (UserKind.PROFESSIONAL, employers_accounts_tag),
            (UserKind.PROFESSIONAL, prescribers_accounts_tag),
            (UserKind.JOB_SEEKER, job_seekers_accounts_tag),
        ],
    )
    @override_settings(SHOW_DEMO_ACCOUNTS_BANNER=True)
    def test_can_login_to_demo_account(self, client, load_test_users, user_kind, template_tag):
        password = "password"

        for account in template_tag():
            email = account["email"]
            user = User.objects.get(kind=user_kind, email=email)
            assert authenticate(email=email, password=password) == user

            response = client.post(
                account["action_url"], {"login": email, "password": password, "demo_banner_account": True}
            )
            # NOTE: Login redirects tested elsewhere.
            assert response.status_code == 302
            assert get_user(client).is_authenticated is True


@freeze_time("2026-01-01")
class TestCriterionCertificationBadge:
    def test_accepted_job_app_certified(self):
        criterion = IAESelectedAdministrativeCriteriaFactory(criteria_certified=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            eligibility_diagnosis=criterion.eligibility_diagnosis,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
            state=JobApplicationState.ACCEPTED,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            CERTIFIED_BADGE_HTML,
        )

    def test_accepted_job_app_certified_in_the_past(self):
        criterion = IAESelectedAdministrativeCriteriaFactory(
            criteria_certified=True,
            certification_period=InclusiveDateRange(date(2025, 9, 1), date(2025, 12, 31)),
            eligibility_diagnosis__created_at=datetime(2025, 8, 31, tzinfo=UTC),
        )
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            eligibility_diagnosis=criterion.eligibility_diagnosis,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
            hiring_start_at=date(2025, 12, 31),
            state=JobApplicationState.ACCEPTED,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            CERTIFIED_BADGE_HTML,
        )

    def test_accepted_job_app_not_certified(self):
        criterion = IAESelectedAdministrativeCriteriaFactory(criteria_not_certified=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            eligibility_diagnosis=criterion.eligibility_diagnosis,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
            state=JobApplicationState.ACCEPTED,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            NOT_CERTIFIED_BADGE_HTML,
        )

    def test_accepted_job_app_without_hiring_start_at(self):
        """This happens for job applications imported together with PE approvals (origin="pe_approval")"""
        criterion = IAESelectedAdministrativeCriteriaFactory(criteria_certified=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            hiring_start_at=None,
            state=JobApplicationState.ACCEPTED,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            NOT_CERTIFIED_BADGE_HTML,
        )

    def test_certified_complete_eligibility_diagnosis_duration(self):
        criterion = IAESelectedAdministrativeCriteriaFactory(criteria_certified=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            state=JobApplicationState.ACCEPTED,
            eligibility_diagnosis=criterion.eligibility_diagnosis,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            CERTIFIED_BADGE_HTML,
        )

    def test_certified_partial_eligibility_diagnosis_duration(self):
        criterion = IAESelectedAdministrativeCriteriaFactory(
            criteria_certified=True,
            certification_period=InclusiveDateRange(date(2026, 1, 1), date(2026, 1, 31)),
        )
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            certified_temporarily_html(date(2026, 1, 31)),
        )
        with freeze_time("2026-02-01"):
            assertHTMLEqual(
                criterion_certification_badge(criterion, job_application),
                EXPIRED_CERTIFICATION_HTML,
            )

    def test_certification_starts_in_the_future(self):
        criterion = IAESelectedAdministrativeCriteriaFactory(
            criteria_certified=True,
            certification_period=InclusiveDateRange(date(2026, 2, 1), date(2026, 2, 28)),
        )
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            certified_in_the_future_html(date(2026, 2, 1)),
        )
        with freeze_time("2026-02-01"):
            assertHTMLEqual(
                criterion_certification_badge(criterion, job_application),
                certified_temporarily_html(date(2026, 2, 28)),
            )

    def test_not_certified(self):
        criterion = IAESelectedAdministrativeCriteriaFactory(criteria_not_certified=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            state=JobApplicationState.ACCEPTED,
            eligibility_diagnosis=criterion.eligibility_diagnosis,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            NOT_CERTIFIED_BADGE_HTML,
        )

    def test_certification_error(self):
        criterion = IAESelectedAdministrativeCriteriaFactory(criteria_certification_error=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            state=JobApplicationState.ACCEPTED,
            eligibility_diagnosis=criterion.eligibility_diagnosis,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            CERTIFICATION_ERROR_BADGE_HTML,
        )

    def test_certification_in_progress(self):
        criterion = IAESelectedAdministrativeCriteriaFactory()
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            state=JobApplicationState.ACCEPTED,
            eligibility_diagnosis=criterion.eligibility_diagnosis,
            job_seeker=criterion.eligibility_diagnosis.job_seeker,
        )
        assertHTMLEqual(
            criterion_certification_badge(criterion, job_application),
            IN_PROGRESS_BADGE_HTML,
        )


class TestDORAOrientationURL:
    def test_dora_source_with_source_link(self, settings):
        source = GenericReferenceItemFactory(kind=GenericReferenceItemKind.SOURCE, value="dora")
        service = ServiceFactory.build(
            source=source,
            source_link="https://dora.inclusion.gouv.fr/services/mon-service",
            uid="my-uid",
        )
        url = dora_orientation_url(service, orientation_jwt=None, source="foo")
        expected = (
            f"{settings.DORA_WWW_BASE_URL}/services/mon-service/orienter?mtm_campaign=lesemplois&mtm_kwd=service-foo"
        )
        assert url == expected

    def test_non_dora_source(self, settings):
        source = GenericReferenceItemFactory(kind=GenericReferenceItemKind.SOURCE, value="di")
        service = ServiceFactory.build(source=source, uid="my-uid")
        url = dora_orientation_url(service, orientation_jwt=None, source="bar")
        expected = (
            f"{settings.DORA_WWW_BASE_URL}/services/di--my-uid/orienter?mtm_campaign=lesemplois&mtm_kwd=service-bar"
        )
        assert url == expected

    def test_with_orientation_jwt(self, settings):
        source = GenericReferenceItemFactory(kind=GenericReferenceItemKind.SOURCE, value="dora")
        service = ServiceFactory.build(
            source=source,
            source_link="https://dora.inclusion.gouv.fr/services/mon-service",
            uid="my-uid",
        )
        url = dora_orientation_url(service, orientation_jwt="my-jwt", source="foo")
        parsed = urlsplit(url)
        assert parsed.path == django_reverse("nexus:auto_login")
        next_url_query = QueryDict(urlsplit(QueryDict(parsed.query)["next_url"]).query)
        assert next_url_query["op"] == "my-jwt"
        assert next_url_query["mtm_campaign"] == "lesemplois"

    def test_mtm_source_param(self, settings):
        source = GenericReferenceItemFactory(kind=GenericReferenceItemKind.SOURCE, value="di")
        service = ServiceFactory.build(source=source, uid="my-uid")
        url = dora_orientation_url(service, orientation_jwt=None, source="prescriber")
        assert "mtm_kwd=service-prescriber" in url


class TestUrlizeNewTab:
    def test_plain_text_unchanged(self):
        result = urlize_new_tab("Hello world")
        assert "target=" not in result
        assert "<a" not in result

    def test_url_gets_new_tab_attrs(self):
        result = urlize_new_tab("Visit https://example.com for info")
        assert (
            result
            == 'Visit <a target="_blank" rel="noopener noreferrer" href="https://example.com" rel="nofollow">https://example.com</a> for info'  # noqa: E501
        )

    def test_multiple_urls(self):
        result = urlize_new_tab("See https://example.com and https://other.com")
        assert result.count('target="_blank"') == 2
        assert result.count('rel="noopener noreferrer"') == 2
