from django import forms
from django.template import Context, Template
from pytest_django.asserts import assertHTMLEqual

from itou.utils.widgets import EasyMDEEditor


class TestEasyMDEEditor:
    def test_basic(self):
        class MyForm(forms.Form):
            description = forms.CharField(widget=EasyMDEEditor)

        form = MyForm()
        assertHTMLEqual(
            str(form),
            """
            <div>
            <label for="id_description">Description :</label>
            <textarea class="easymde-box" cols="40" id="id_description" name="description" required rows="10">
            </div>
            """,
        )

    def test_merge_with_attrs_class(self):
        class MyForm(forms.Form):
            description = forms.CharField(widget=EasyMDEEditor())

        form = MyForm()
        t = Template(
            """
            {% load django_bootstrap5 %}
            {% bootstrap_form form %}
            """
        )
        assertHTMLEqual(
            t.render(Context({"form": form})),
            """
            <div class="form-group form-group-required">
            <label class="form-label" for="id_description">
            Description
            </label>
            <textarea
                class="easymde-box form-control"
                cols="40"
                id="id_description"
                name="description"
                required
                rows="10"
                placeholder="Description">
            </div>
            """,
        )
