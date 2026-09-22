from django import forms

from itou.directory.enums import ContactSubject


class ContactMessageForm(forms.Form):
    subject = forms.ChoiceField(
        label="Objet",
        choices=[("", "Choisir un objet…")] + list(ContactSubject.choices),
    )
    custom_subject = forms.CharField(label="Précisez l'objet", required=False, max_length=255)
    body = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={"placeholder": "Votre message…", "rows": 6}),
        max_length=5000,
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("subject") == ContactSubject.OTHER and not cleaned_data.get("custom_subject"):
            self.add_error("custom_subject", "Précisez l'objet de votre message.")
        elif cleaned_data.get("subject") != ContactSubject.OTHER:
            cleaned_data["custom_subject"] = ""
        return cleaned_data
