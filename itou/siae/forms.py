from django import forms
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from itou.cities.models import City


class SiaeSearchForm(forms.Form):

    DISTANCES = [100, 75, 50, 25, 15, 10, 5]
    DISTANCE_CHOICES = [(i, _(f"{i} Km")) for i in DISTANCES]
    CITY_AUTOCOMPLETE_SOURCE_URL = reverse_lazy('city:autocomplete')

    distance = forms.ChoiceField(
        choices=DISTANCE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-control',
        }),
    )

    # The hidden `city` field is populated by the autocomplete JavaScript mechanism,
    # see `city_autocomplete_field.js`.
    city = forms.CharField(
        widget=forms.HiddenInput(attrs={
            'class': 'js-city-autocomplete-hidden',
        }),
    )
    city_autocomplete = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'js-city-autocomplete-input form-control',
            'data-autocomplete-source-url': CITY_AUTOCOMPLETE_SOURCE_URL,
            'placeholder': _("Autour de (Arras, Bobigny, Strasbourg…)"),
        }),
    )

    def clean_city(self):
        slug = self.cleaned_data['city']
        try:
            return City.active_objects.get(slug=slug)
        except City.DoesNotExist:
            raise forms.ValidationError(_("Cette ville n'existe pas."))
