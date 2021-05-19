import django.forms as forms
from django.urls import reverse_lazy

from itou.cities.models import City
from itou.users.models import User


class AddressFormMixin(forms.Form):

    ALL_CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:cities")

    # The hidden `city` field is populated by the autocomplete JavaScript mechanism,
    # see `city_autocomplete_field.js`.
    city = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"class": "js-city-autocomplete-hidden"}))

    city_name = forms.CharField(
        label="Ville",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "js-city-autocomplete-input form-control",
                "data-autocomplete-source-url": ALL_CITY_AUTOCOMPLETE_SOURCE_URL,
                "data-autosubmit-on-enter-pressed": 0,
                "placeholder": "Nom de la ville",
                "autocomplete": "off",
            }
        ),
    )

    address_line_1 = forms.CharField(
        required=False,
        max_length=User._meta.get_field("address_line_1").max_length,
        label="Adresse",
    )

    address_line_2 = forms.CharField(
        required=False,
        max_length=User._meta.get_field("address_line_2").max_length,
        label="Complément d'adresse",
    )

    post_code = forms.CharField(
        required=False,
        max_length=User._meta.get_field("post_code").max_length,
        label="Code postal",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Needed for proper auto-completion when `AddressFormMixin` is used with
        # a ModelForm which has an instance existing in DB.
        if hasattr(self, "instance") and hasattr(self.instance, "city") and hasattr(self.instance, "department"):
            self.initial["city_name"] = self.instance.city
            # Populate the hidden `city` field.
            city = City.objects.filter(name=self.instance.city, department=self.instance.department).first()
            if city:
                self.initial["city"] = city.slug

    def clean(self):
        cleaned_data = super().clean()

        city_slug = cleaned_data["city"]

        if city_slug:
            try:
                # TODO: use more intuitive field names.
                # Override the `city` field in `cleaned_data` with the real city name
                # because the value will be stored in `AddressMixin.city`.
                cleaned_data["city"] = City.objects.get(slug=city_slug).name
            except City.DoesNotExist:
                raise forms.ValidationError({"city_name": "Cette ville n'existe pas."})

        # Basic check of address fields.
        addr1, addr2, post_code, city = (
            cleaned_data["address_line_1"],
            cleaned_data["address_line_2"],
            cleaned_data["post_code"],
            cleaned_data["city"],
        )

        valid_address = all([addr1, post_code, city])
        empty_address = not any([addr1, addr2, post_code, city])
        if not empty_address and not valid_address:
            if not addr1:
                self.add_error("address_line_1", "Adresse : ce champ est obligatoire.")
            if not post_code:
                self.add_error("post_code", "Code postal : ce champ est obligatoire.")
            if not city_slug:
                self.add_error("city_name", "Ville : ce champ est obligatoire.")
