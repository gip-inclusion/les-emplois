from django import forms

from dal import autocomplete


class SiaeSearchForm(forms.Form):

    city = forms.ChoiceField(widget=autocomplete.Select2(url='autocomplete:cities'))
