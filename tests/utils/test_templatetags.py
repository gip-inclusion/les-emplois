import pytest
from django import forms
from django.template import Context, Template
from django.urls import URLPattern, URLResolver, get_resolver

from itou.utils.templatetags.nav import NAV_ENTRIES


def test_matomo_event():
    template = Template('{% load matomo %}<a href="#" {% matomo_event "category" "action" "option" %} >')
    expected_render = (
        '<a href="#" data-matomo-event="true" data-matomo-category="category" '
        'data-matomo-action="action" data-matomo-option="option" >'
    )
    assert template.render(Context({})) == expected_render


class TestButtonsForm:
    def test_itou_buttons_form(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form %}")
        assert template.render(Context({})) == snapshot(name="no params")

    def test_itou_buttons_form_reset_url(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form %}")
        assert template.render(Context({})) == snapshot(name="default_reset_url")

        template = Template('{% load buttons_form %}{% itou_buttons_form reset_url="/reset" %}')
        assert template.render(Context({})) == snapshot(name="reset_url")

    def test_itou_buttons_with_primary_name_and_value(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form primary_name="name" primary_value="1" %}')
        assert template.render(Context({})) == snapshot(name="with_primary_name_and_value")

    def test_itou_buttons_with_primary_aria_label(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form primary_aria_label="label" %}')
        assert template.render(Context({})) == snapshot(name="with_primary_aria_label")

    def test_itou_buttons_with_primary_url(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form primary_url="/next" %}')
        assert template.render(Context({})) == snapshot(name="with_primary_url")

    def test_itou_buttons_with_primary_name_value_aria_label_and_matomo_tags(self, snapshot):
        template = Template(
            "{% load buttons_form %}"
            '{% itou_buttons_form primary_name="name" primary_value="1" '
            'primary_aria_label="label" '
            'matomo_category="category" matomo_action="action" matomo_name="name" %}'
        )
        assert template.render(Context({})) == snapshot(name="with_primary_name_value_aria_label_and_matomo_tags")

    def test_itou_buttons_with_primary_disabled(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form primary_disabled=True %}")
        assert template.render(Context({})) == snapshot(name="with_primary_disabled")

    def test_itou_buttons_with_secondary_aria_label(self, snapshot):
        template = Template(
            '{% load buttons_form %}{% itou_buttons_form secondary_url="/prev" secondary_aria_label="label" %}'
        )
        assert template.render(Context({})) == snapshot(name="with_secondary_aria_label")

    def test_itou_buttons_with_secondary_url(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form secondary_url="/do" %}')
        assert template.render(Context({})) == snapshot(name="no_form_title")

    def test_itou_buttons_with_secondary_name_and_value(self, snapshot):
        template = Template('{% load buttons_form %}{% itou_buttons_form secondary_name="name" secondary_value="1" %}')
        assert template.render(Context({})) == snapshot(name="with_secondary_name_and_value")

    def test_itou_buttons_matomo_event(self, snapshot):
        template = Template(
            "{% load buttons_form %}"
            '{% itou_buttons_form matomo_category="category" matomo_action="action" matomo_name="name" %}'
        )
        assert template.render(Context({})) == snapshot(name="matomo_event")

    def test_itou_buttons_mandatory_fields_mention(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form show_mandatory_fields_mention=False %}")
        assert template.render(Context({})) == snapshot(name="no_mandatory_fields_mention")


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
        for entry in NAV_ENTRIES.values():
            for urlname in entry.active_view_names:
                assert urlname in named_urls

    def test_all_urls_registered(self, named_urls):
        # - External apps
        # - Apps without HTML pages
        # - HTML pages for anonymous users
        # - HTML pages for which there is no menu entry (yet).
        excluded_namespaces = {
            "admin",
            "announcements",
            "anymail",
            "api",
            "autocomplete",
            "dashboard",
            "france_connect",
            "geiq",
            "gps",
            "hijack",
            "home",  # The dashboard index is used instead.
            "inclusion_connect",
            "itou_staff_views",
            "login",
            "pe_connect",
            "pro_connect",
            "rdv_insertion",
            "releases",
            "siae_evaluations_views",
            "signup",
            "stats",
            "status",
            "users",  # GPS
            "v1",  # API
            "welcoming_tour",
        }
        not_html_urlnames = {
            # HTMX fragments
            "apply:add_prior_action",
            "apply:delete_prior_action",
            "apply:geiq_eligibility_criteria",
            "apply:modify_prior_action",
            "apply:rdv_insertion_invite",
            "apply:rdv_insertion_invite_for_detail",
            "apply:reload_contract_type_and_options",
            "apply:reload_job_description_fields",
            "apply:reload_qualification_fields",
            "approvals:check_contact_details",
            "approvals:check_prescriber_email",
            "approvals:prolongation_form_for_reason",
            # Redirect only views
            "apply:archive",
            "apply:cancel",
            "apply:send_diagoriente_invite",
            "apply:start",
            "apply:unarchive",
            "approvals:prolongation_request_deny",
            "approvals:prolongation_request_grant",
            "approvals:redirect_to_employee",
            "companies_views:dora_service_redirect",
            "companies_views:hx_dora_services",
            "invitations_views:join_company",
            "invitations_views:join_institution",
            "invitations_views:join_prescriber_organization",
            # Exports
            "apply:list_for_siae_exports_download",
            "apply:list_prescriptions_exports_download",
            "approvals:prolongation_request_report_file",
            # Do not highlight Métiers when viewing company cards:
            # users are likely not viewing their company.
            "companies_views:card",
            "companies_views:job_description_card",
            # Not listed in the menu (yet)
            "prescribers_views:list_accredited_organizations",
            # Anonymous views
            "invitations_views:new_user",
        }
        excluded_urlnames = {
            "accessibility",
            "legal-notice",
            "legal-privacy",
            "legal-terms",
        }
        excluded_namespace_urls = set()
        for namespaced_url in [url for url in named_urls if ":" in url]:
            namespace, _name = namespaced_url.split(":", maxsplit=1)
            if namespace not in excluded_namespaces:
                excluded_namespace_urls.add(namespaced_url)
        expected_urlnames_in_nav = excluded_namespace_urls - not_html_urlnames - excluded_urlnames
        nav_urlnames = {
            active_view_name for entry in NAV_ENTRIES.values() for active_view_name in entry.active_view_names
        }
        assert set(expected_urlnames_in_nav) - set(nav_urlnames) == set()


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
