import uuid

from django import forms

from itou.communications.models import AnnouncementItem
from itou.files.forms import ItouAdminImageInput
from itou.users.enums import UserKind
from itou.utils import constants as global_constants


class AnnouncementItemForm(forms.ModelForm):
    class Meta:
        model = AnnouncementItem
        fields = ["priority", "title", "description", "user_kind_tags", "image", "link"]

    user_kind_tags = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=UserKind.choices,
        label="Utilisateurs concernés",
    )
    image = forms.ImageField(
        required=False,
        widget=ItouAdminImageInput(attrs={"accept": global_constants.SUPPORTED_IMAGE_FILE_TYPES.keys()}),
        label="Capture d'écran",
    )

    def clean_image(self):
        image = self.cleaned_data.get("image", None)
        if image:
            image.name = f"{uuid.uuid4()}.{image.name.split('.')[-1]}"
        return image
