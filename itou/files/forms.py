import pathlib

import pypdf
import pypdf.errors
from django import forms
from django.utils.formats import localize
from django.utils.html import format_html

from itou.utils.constants import ITOU_HELP_CENTER_URL, MB


class ItouFileInput(forms.FileInput):
    template_name = "utils/widgets/file_input.html"

    def __init__(self, *, attrs=None, content_type, max_upload_size_mb):
        if attrs is None:
            attrs = {}
        else:
            attrs = attrs.copy()
        attrs.setdefault("accept", content_type)
        super().__init__(attrs=attrs)
        self.content_type = content_type
        self.max_upload_size_mb = max_upload_size_mb

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["content_type"] = self.content_type
        context["widget"]["max_upload_size_mb"] = self.max_upload_size_mb
        return context


class ItouFileField(forms.FileField):
    def __init__(self, *args, content_type, max_upload_size, **kwargs):
        max_upload_size_mb = max_upload_size / MB
        kwargs.setdefault("widget", ItouFileInput(content_type=content_type, max_upload_size_mb=max_upload_size_mb))
        super().__init__(*args, **kwargs)
        self.content_type = content_type
        self.max_upload_size = max_upload_size
        self.max_upload_size_mb = max_upload_size_mb
        if content_type == "application/pdf" and not self.help_text:
            self.help_text = format_html(
                """
                <p>
                    <i class="ri-question-line mr-1"></i>
                    Ce fichier n'est pas un PDF ?
                    <a href="%s"
                       target="_blank"
                       rel="noopener"
                       class="matomo-event has-external-link"
                       matomo-category="ajout-fichier-candidature"
                       matomo-action="clic"
                       matomo-option="clic-sur-lien-aide-pdf"
                       aria-label="Découvrez comment le convertir (ouverture dans un nouvel onglet)">
                        Découvrez comment le convertir.
                    </a>
                </p>
               """,
                f"{ITOU_HELP_CENTER_URL}/articles/16875396981777--Convertir-votre-document-en-format-PDF",
            )

    def clean(self, data, initial=None):
        cleaned_data = super().clean(data, initial=initial)
        if data:
            if data.size > self.max_upload_size:
                raise forms.ValidationError(f"Le fichier doit faire moins de {localize(self.max_upload_size_mb)} Mo.")
            if self.content_type == "application/pdf":
                if pathlib.Path(data.name).suffix != ".pdf":
                    raise forms.ValidationError("Le fichier doit avoir l’extension “.pdf”.")
                if data.content_type != self.content_type:
                    raise forms.ValidationError("Le fichier doit être de type “application/pdf”.")
                try:
                    pypdf.PdfReader(data)
                except pypdf.errors.PyPdfError:
                    raise forms.ValidationError("Le fichier doit être un fichier PDF valide.")
            else:
                raise NotImplementedError
        return cleaned_data
