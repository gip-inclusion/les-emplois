import django.forms as forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy

from itou.cities.models import City


class AddressFormMixin(forms.Form):

    ALL_CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:cities")

    city = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"class": "js-city-autocomplete-hidden"}))

    city_name = forms.CharField(
        label=gettext_lazy("Ville"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "js-city-autocomplete-input form-control",
                "data-autocomplete-source-url": ALL_CITY_AUTOCOMPLETE_SOURCE_URL,
                "placeholder": gettext_lazy("Nom de la ville"),
                "autocomplete": "off",
            }
        ),
    )

    address_line_1 = forms.CharField(
        required=False,
        max_length=get_user_model()._meta.get_field("address_line_1").max_length,
        label=gettext_lazy("Adresse"),
    )

    address_line_2 = forms.CharField(
        required=False,
        max_length=get_user_model()._meta.get_field("address_line_2").max_length,
        label=gettext_lazy("Complément d'adresse"),
    )

    post_code = forms.CharField(
        required=False,
        max_length=get_user_model()._meta.get_field("post_code").max_length,
        label=gettext_lazy("Code postal"),
    )

    def clean_city(self):
        slug = self.cleaned_data["city"]
        # Addresses are optional: check only if smth is entered
        if slug:
            try:
                return City.objects.get(slug=slug).name
            except City.DoesNotExist:
                raise forms.ValidationError(gettext_lazy("Cette ville n'existe pas."))
        return ""

    def clean(self):
        cleaned_data = super().clean()
        # Basic check of address fields
        addr1, addr2, zip, city = (
            cleaned_data["address_line_1"],
            cleaned_data["address_line_2"],
            cleaned_data["post_code"],
            cleaned_data["city"],
        )
        valid = all([addr1, zip, city]) or not any([addr1, addr2, zip, city])

        if not valid:
            raise (ValidationError(gettext_lazy("Adresse incomplète")))
