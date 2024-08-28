from django import forms
from django_select2.forms import Select2Widget


class FilterForm(forms.Form):
    job_seeker = forms.ChoiceField(
        required=False,
        label="Nom",
        widget=Select2Widget(
            attrs={
                "data-placeholder": "Nom du salarié",
            }
        ),
    )

    def __init__(self, job_seeker_qs, data, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.fields["job_seeker"].choices = [
            (job_seeker.pk, job_seeker.get_full_name())
            for job_seeker in job_seeker_qs.order_by("first_name", "last_name")
            if job_seeker.get_full_name()
        ]
