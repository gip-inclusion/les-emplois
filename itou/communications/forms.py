import pathlib
import uuid

from django import forms

from itou.communications.models import AnnouncementItem
from itou.files.forms import ItouAdminImageInput
from itou.users.enums import UserKind
from itou.utils import constants as global_constants


def user_kind_tag_choices():
    valid_choices = [UserKind.JOB_SEEKER, UserKind.PRESCRIBER, UserKind.EMPLOYER]
    return [(u.value, u.label) for u in valid_choices]


class AnnouncementItemForm(forms.ModelForm):
    user_kind_tags = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=user_kind_tag_choices,
        label="Utilisateurs concernés",
    )
    image = forms.ImageField(
        required=False,
        widget=ItouAdminImageInput(attrs={"accept": global_constants.SUPPORTED_IMAGE_FILE_TYPES}),
        label="Capture d'écran",
    )

    class Meta:
        model = AnnouncementItem
        fields = ["priority", "title", "description", "user_kind_tags", "image", "image_alt_text", "link"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            extension = pathlib.Path(image.name).suffix
            image.name = f"{uuid.uuid4()}{extension}"
        return image
