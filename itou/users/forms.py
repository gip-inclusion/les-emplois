from django.core.exceptions import ValidationError
from django.forms import widgets
from django.utils.safestring import mark_safe

from itou.asp.forms import BirthPlaceWithBirthdateModelForm
from itou.users.models import JobSeekerProfile, User
from itou.utils import constants as global_constants
from itou.utils.widgets import DuetDatePickerWidget


def validate_francetravail_email(email):
    allowed_suffixes = (
        global_constants.POLE_EMPLOI_EMAIL_SUFFIX,
        global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX,
    )
    if not email.endswith(allowed_suffixes):
        raise ValidationError("L'adresse e-mail doit être une adresse Pôle emploi ou France Travail.")
    return email


class JobSeekerProfileFieldsMixin:
    """Mixin to add JobSeekerProfile's fields to an User ModelForm"""

    PROFILE_FIELDS = []

    def __init__(self, *args, instance=None, **kwargs):
        profile_initial = {}
        if instance:
            for field in self.PROFILE_FIELDS:
                profile_initial[field] = getattr(instance.jobseeker_profile, field)
        initial = kwargs.pop("initial", {})
        super().__init__(*args, instance=instance, initial=profile_initial | initial, **kwargs)
        for field in self.PROFILE_FIELDS:
            if field not in self.fields:
                self.fields[field] = JobSeekerProfile._meta.get_field(field).formfield()

    def save(self, commit=True):
        user = super().save(commit=commit)
        for field in self.PROFILE_FIELDS:
            setattr(user.jobseeker_profile, field, self.cleaned_data[field])
        if commit:
            user.jobseeker_profile.save(update_fields=self.PROFILE_FIELDS)

    @property
    def cleaned_data_from_profile_fields(self):
        return {k: v for k, v in self.cleaned_data.items() if k in self.PROFILE_FIELDS}

    @property
    def cleaned_data_without_profile_fields(self):
        return {k: v for k, v in self.cleaned_data.items() if k not in self.PROFILE_FIELDS}

    def _post_clean(self):
        super()._post_clean()
        if hasattr(self.instance, "jobseeker_profile"):
            jobseeker_profile = self.instance.jobseeker_profile
        else:
            jobseeker_profile = JobSeekerProfile()
        for k, v in self.cleaned_data_from_profile_fields.items():
            setattr(jobseeker_profile, k, v)
        # super()._post_clean() calls full_clean() on self.instance, which calls self.instance.clean_fields()
        # Let's do the same on self.instance.jobseeker_profile (but only for our fields)
        try:
            jobseeker_profile.clean_fields(
                exclude={f.name for f in JobSeekerProfile._meta.fields if f.name not in self.PROFILE_FIELDS}
            )
        except ValidationError as e:
            self._update_errors(e)
        try:
            jobseeker_profile.validate_constraints()
        except ValidationError as e:
            self._update_errors(e)


class JobSeekerProfileModelForm(JobSeekerProfileFieldsMixin, BirthPlaceWithBirthdateModelForm):
    PROFILE_FIELDS = ["birthdate", "birth_place", "birth_country"]
    REQUIRED_FIELDS = ["title", "first_name", "last_name", "birthdate"]

    class Meta:
        model = User
        fields = ["title", "first_name", "last_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.readonly_pii_fields = self.instance.jobseeker_profile.readonly_pii_fields() if self.instance.pk else []
        birthdate = self.fields["birthdate"]
        birthdate.widget = DuetDatePickerWidget(
            attrs={
                "min": DuetDatePickerWidget.min_birthdate(),
                "max": DuetDatePickerWidget.max_birthdate(),
            }
        )
        birthdate.help_text = "Au format JJ/MM/AAAA, par exemple 20/12/1978."
        for fieldname in self.REQUIRED_FIELDS:
            try:
                self.fields[fieldname].required = True
            except KeyError:
                pass

        for fieldname, field in self.fields.items():
            if fieldname in self.readonly_pii_fields:
                field.disabled = True
                if fieldname in ["birth_place", "birth_country"]:
                    # No need to load a select2, if we’re only going to disable it.
                    field.widget = widgets.Select()
                    # Avoid constructing the choices.
                    modelfield = self.instance.jobseeker_profile._meta.get_field(fieldname)
                    accessor = modelfield.attname
                    value = getattr(self.instance.jobseeker_profile, accessor)
                    field.queryset = field.queryset.filter(pk=value)

    def clean(self):
        super().clean()
        if "pole_emploi_id" in self.fields and "lack_of_pole_emploi_id_reason" in self.fields:
            JobSeekerProfile.clean_pole_emploi_fields(self.cleaned_data)

    def pole_emploi_id_error(self):
        if self.has_error("pole_emploi_id"):
            return mark_safe("""
                <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                    <p>
                        <strong>L’identifiant France Travail n’est pas valide</strong>
                    </p>
                    <p class="mb-0">
                        Pour continuer, veuillez renseigner un identifiant qui respecte l’un des deux formats
                        autorisés : 8 caractères (7 chiffres suivis d'une lettre ou d'un chiffre) ou 11 chiffres.
                    </p>
                </div>
            """)
        return None
