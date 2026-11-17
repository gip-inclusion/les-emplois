from django import forms
from django.template import Context, Template
from pytest_django.asserts import assertHTMLEqual, assertInHTML

from itou.users.models import User
from itou.utils.widgets import EasyMDEEditor, RemoteAutocompleteSelect2Widget


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
            </textarea>
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
                rows="10">
            </textarea>
            </div>
            """,
        )


class TestRemoteAutocompleteSelect2Widget:
    def test_null_byte(self):
        class AutoCompleteForm(forms.Form):
            field = forms.ModelChoiceField(
                queryset=User.objects.all(),
                to_field_name="last_name",
                widget=RemoteAutocompleteSelect2Widget(),
            )

        form = AutoCompleteForm({"field": "\x00"})
        assertInHTML(
            """
            <ul class="errorlist" id="id_field_error">
            <li>Le caractère nul n’est pas autorisé.</li>
            </ul>
            """,
            str(form),
        )

    def test_char_instead_of_int(self):
        class AutoCompleteForm(forms.Form):
            field = forms.ModelChoiceField(
                queryset=User.objects.all(),
                widget=RemoteAutocompleteSelect2Widget(),
            )

        form = AutoCompleteForm({"field": "a"})
        assertInHTML(
            """
            <ul class="errorlist" id="id_field_error">
            <li>Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.</li>
            </ul>
            """,
            str(form),
        )

    def test_invalid_uuid(self):
        class AutoCompleteForm(forms.Form):
            field = forms.ModelChoiceField(
                queryset=User.objects.all(),
                to_field_name="public_id",
                widget=RemoteAutocompleteSelect2Widget(),
            )

        form = AutoCompleteForm({"field": "0"})
        assertInHTML(
            """
            <ul class="errorlist" id="id_field_error">
            <li>Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.</li>
            </ul>
            """,
            str(form),
        )
