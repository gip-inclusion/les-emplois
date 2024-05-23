from django.core.exceptions import ValidationError

from itou.users.models import JobSeekerProfile
from itou.utils import constants as global_constants


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
