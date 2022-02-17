import re
from xml.dom import ValidationErr

import django.forms as forms
from django.conf import settings


class ResumeFormMixin(forms.Form):
    resume_link = forms.URLField(
        label="CV (optionnel)",
        required=False,
    )

    class Meta:
        fields = [
            "resume_link",
        ]

    def clean_resume_link(self):
        resume_link = self.cleaned_data["resume_link"]
        # ensure the CV has been uploaded via our S3 platform and is not a link to a 3rd party website
        if not settings.S3_STORAGE_ENDPOINT_DOMAIN in resume_link:
            self.add_error(
                "resume_link", forms.ValidationError("Le CV proposé ne provient pas d'une source de confiance.")
            )
        return resume_link
