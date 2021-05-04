import re

import django.forms as forms


class ResumeFormMixin(forms.Form):
    """
    Handles resume field for job applications
    """

    resume_link = forms.URLField(
        label=gettext_lazy("CV (optionnel)"),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "https://www.mon_cv.fr/dfROS"}),
    )

    class Meta:
        fields = [
            "resume_link",
        ]

    def clean_resume_link(self):
        """
        PE developed a platform to host job seeker's documents such as resumes.
        It looks like a Cloud drive and offers the possibility to share
        documents with their own link. PE prescribers often use it.
        Unfortunately, documents are not public but limited to connected PE prescribers!
        """
        resume_link = self.cleaned_data["resume_link"]
        pole_emploi_pattern = r"^https?://.*\.pole-emploi\.intra/.*\.{0,7}"
        match = re.search(pole_emploi_pattern, resume_link)
        if match:
            error = forms.ValidationError(
                (
                    "Les CV hébergés par l'intranet de Pôle emploi ne sont pas publics. "
                    "Indiquez une autre adresse ou laissez ce champ vide pour continuer."
                )
            )
            self.add_error("resume_link", error)
        return resume_link
