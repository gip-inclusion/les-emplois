import pytest  # noqa
from django.template import Context, Template


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

    def test_itou_buttons_with_primary_url_name_value_aria_label_and_matomo_tags(self, snapshot):
        template = Template(
            "{% load buttons_form %}"
            '{% itou_buttons_form primary_url="/next" primary_name="name" primary_value="1" '
            'primary_aria_label="label" '
            'matomo_category="category" matomo_action="action" matomo_name="name" %}'
        )
        assert template.render(Context({})) == snapshot(name="with_primary_url_name_value_aria_label_and_matomo_tags")

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
        template = Template(
            (
                '{% load buttons_form %}{% itou_buttons_form secondary_url="/do" '
                'secondary_name="name" secondary_value="1" %}'
            )
        )
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

    def test_save_and_quit_modal_content(self, snapshot):
        template = Template("{% load buttons_form %}{% itou_buttons_form modal_content_save_and_quit=True %}")
        assert template.render(Context({})) == snapshot(name="save_and_quit_modal_content")
