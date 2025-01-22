from django import forms
from django_select2.forms import Select2Widget

from itou.users.models import User


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
