import pytest
from django import forms
from django.contrib.auth import authenticate, get_user
from django.core.management import call_command
from django.template import Context, Template
from django.test import override_settings
from django.urls import URLPattern, URLResolver, get_resolver

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.templatetags.demo_accounts import (
    employers_accounts_tag,
    job_seekers_accounts_tag,
    prescribers_accounts_tag,
)
from itou.utils.templatetags.nav import NAV_ENTRIES
from tests.utils.test import pretty_indented


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
    def named_urls(self):
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
            no_nir = forms.BooleanField()
            nir = forms.CharField()

        template = Template('{% load theme_inclusion %}{% collapse_field form.no_nir target_id="nir" %}')
        assert template.render(Context({"form": NIRForm()})) == snapshot()

    def test_collapse_field_multiple_controls(self):
        class NIRForm(forms.Form):
            no_nir = forms.BooleanField()
            nir = forms.CharField()

        field_markup = '{% collapse_field form.no_nir target_id="nir" %}'
        template = Template("{% load theme_inclusion %}" + field_markup * 2)
        with pytest.raises(NotImplementedError):
            template.render(Context({"form": NIRForm()}))


@pytest.fixture
def load_test_users():
    call_command("loaddata", "05_test_users.json")
    call_command("loaddata", "06_confirmed_emails.json")


class TestDemoAccount:
    @pytest.mark.parametrize(
        "user_kind,template_tag",
        [
            (UserKind.EMPLOYER, employers_accounts_tag),
            (UserKind.PRESCRIBER, prescribers_accounts_tag),
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
