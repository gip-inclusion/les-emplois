from django import forms
from django.urls import reverse_lazy
from django.utils.text import format_lazy
from django_select2.forms import Select2Widget

from itou.companies import enums as companies_enums
from itou.companies.models import Company
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.widgets import RemoteAutocompleteSelect2Widget


class GpsUserSearchForm(forms.Form):
    # NB we need to inherit from forms.Form if we want the attributes
    # to be added to the a Form using this mixin (django magic)

    user = forms.ModelChoiceField(
        queryset=User.objects.filter(kind=UserKind.JOB_SEEKER),
        label="Nom et prénom du bénéficiaire",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": format_lazy("{}?select2=", reverse_lazy("autocomplete:gps_users")),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 2,
                "lang": "",  # Needed to override the noResults i18n translation in JS.
                "id": "js-search-user-input",
            },
        ),
        required=True,
    )

    is_referent = forms.BooleanField(label="Se rattacher comme référent", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        singleton = Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)
        self.fields["user"].widget.attrs["data-no-results-url"] = (
            reverse_lazy("apply:start", kwargs={"company_pk": singleton.pk}) + "?gps=true"
        )


class MembershipsFiltersForm(forms.Form):
    beneficiary = forms.ChoiceField(
        required=False,
        label="Nom du bénéficiaire",
        widget=Select2Widget(
            attrs={"data-placeholder": "Nom du bénéficiaire"},
        ),
    )

    def __init__(self, memberships_qs, *args, **kwargs):
        self.queryset = memberships_qs
        super().__init__(*args, **kwargs)
        self.fields["beneficiary"].choices = self._get_beneficiary_choices()

    def filter(self):
        queryset = self.queryset
        if beneficiary := self.cleaned_data.get("beneficiary"):
            queryset = queryset.filter(follow_up_group__beneficiary_id=beneficiary, is_active=True)
        return queryset

    def _get_beneficiary_choices(self):
        beneficiaries_ids = self.queryset.values_list("follow_up_group__beneficiary_id", flat=True)
        users = User.objects.filter(id__in=beneficiaries_ids)
        users = [(user.id, user.get_full_name().title()) for user in users if user.get_full_name()]
        return sorted(users, key=lambda user: user[1])
