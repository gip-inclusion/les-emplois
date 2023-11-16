import pytest  # noqa
from django.template import Context, Template


def test_matomo_event():
    template = Template('{% load matomo %}<a href="#" {% matomo_event "category" "action" "option" %} >')
    expected_render = (
        '<a href="#" data-matomo-event="true" data-matomo-category="category" '
        'data-matomo-action="action" data-matomo-option="option" >'
    )
    assert template.render(Context({})) == expected_render
