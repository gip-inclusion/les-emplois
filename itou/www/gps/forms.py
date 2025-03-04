from django import forms
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.safestring import mark_safe
from django_select2.forms import Select2Widget

from itou.gps.models import FollowUpGroupMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.widgets import DuetDatePickerWidget, RemoteAutocompleteSelect2Widget
from itou.www.gps.utils import get_all_collegues


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


class FollowUpGroupMembershipForm(forms.ModelForm):
    ONGOING_CHOICES = (("True", "Accompagnement en cours"), ("False", "Accompagnement terminé"))
    is_ongoing = forms.ChoiceField(
        label="Date de fin",
        widget=forms.RadioSelect(attrs={"data-disable-target": "duet-date-picker[identifier=id_ended_at]"}),
        choices=ONGOING_CHOICES,
    )

    class Meta:
        model = FollowUpGroupMembership
        fields = ["started_at", "ended_at", "is_referent", "reason"]
        labels = {
            "is_referent": mark_safe("<strong>Me signaler comme référent</strong>"),
            "started_at": "Date de début",
            "ended_at": "Date de fin",
        }
        widgets = {
            "reason": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Raison de l’accompagnement et/ou actions menées avec la personne."}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["started_at"].widget = DuetDatePickerWidget(attrs={"max": timezone.localdate()})
        self.fields["ended_at"].widget = DuetDatePickerWidget(attrs={"max": timezone.localdate()})
        self.fields["is_ongoing"].initial = self.instance.ended_at is None

    def clean_started_at(self):
        started_at = self.cleaned_data["started_at"]
        if started_at and started_at > timezone.localdate():
            raise forms.ValidationError("Ce champ ne peut pas être dans le futur.")
        return started_at

    def clean_ended_at(self):
        ended_at = self.cleaned_data["ended_at"]
        if ended_at and ended_at > timezone.localdate():
            raise forms.ValidationError("Ce champ ne peut pas être dans le futur.")
        return ended_at

    def clean(self):
        cleaned_data = super().clean()

        if self.errors:
            # No need for additional checks that will not work since some fields are missing from cleaned_data
            return

        # Drop ended_at value if "ongoing" is selected
        if cleaned_data["is_ongoing"] == "True":
            cleaned_data["ended_at"] = None
        else:
            cleaned_data["is_referent"] = False
            if cleaned_data["ended_at"] is None:
                cleaned_data["ended_at"] = timezone.localdate()
            elif cleaned_data["ended_at"] < cleaned_data["started_at"]:
                self.add_error("ended_at", "Cette date ne peut pas être avant la date de début.")


class JoinGroupChannelForm(forms.Form):
    channel = forms.ChoiceField(
        widget=forms.RadioSelect, choices=[(v, v) for v in ["from_collegue", "from_nir", "from_name"]]
    )


class JobSeekersFollowedByCollegueSearchForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=User.objects.filter(kind=UserKind.JOB_SEEKER),
        label="Nom et prénom du bénéficiaire",
        widget=RemoteAutocompleteSelect2Widget(
            attrs={
                "data-ajax--url": reverse_lazy("gps:beneficiaries_autocomplete"),
                "data-ajax--cache": "true",
                "data-ajax--type": "GET",
                "data-minimum-input-length": 2,
                "lang": "",  # Needed to override the noResults i18n translation in JS.
                "id": "js-search-user-input",
            },
        ),
        required=True,
    )

    def __init__(self, *args, organizations, **kwargs):
        self.organizations = organizations
        super().__init__(*args, **kwargs)

    def clean_user(self):
        user = self.cleaned_data["user"]
        all_collegues = get_all_collegues(self.organizations)
        if not FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=user,
            member__in=all_collegues.values("pk"),
        ):
            raise forms.ValidationError("Ce candidat ne peut être suivi.")
        self.job_seeker = user
        return user
