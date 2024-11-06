import io
import pathlib
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from pytest_django.asserts import assertRedirects

from itou.communications.models import AnnouncementCampaign
from itou.files.models import File
from tests.communications.factories import AnnouncementItemFactory


class TestAnnouncementItemAdmin:
    @pytest.fixture
    def black_pixel(self):
        with io.BytesIO() as buf:
            image = Image.new(mode="RGB", size=(1, 1), color=(0, 0, 0))
            image.save(buf, format="png")
            buf.seek(0)
            yield buf.getvalue()

    def test_add_image(self, admin_client, black_pixel):
        response = admin_client.post(
            reverse("admin:communications_announcementcampaign_add"),
            {
                "max_items": 3,
                "start_date": "01/11/2024",
                "live": "on",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "0",
                "items-0-priority": "0",
                "items-0-title": "Bla",
                "items-0-description": "Ho",
                "items-0-image": SimpleUploadedFile("my-image.png", black_pixel, content_type="image/png"),
                "items-0-image_alt_text": "aaa",
                "items-0-link": "",
                "_save": "Enregistrer",
            },
        )
        assertRedirects(response, reverse("admin:communications_announcementcampaign_changelist"))
        campaign = AnnouncementCampaign.objects.get()
        [item] = campaign.items.all()
        filename = pathlib.Path(item.image.name)
        assert uuid.UUID(filename.stem)  # Did not use the provided filename
        assert filename.suffix == ".png"
        file = File.objects.get()
        assert file.key.startswith("news-images/")

    def test_change_image(self, admin_client, black_pixel):
        item = AnnouncementItemFactory(with_image=True)
        url = reverse("admin:communications_announcementcampaign_change", args=(item.campaign_id,))
        response = admin_client.post(
            url,
            {
                "max_items": 3,
                "start_date": "01/11/2024",
                "live": "on",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "1",
                "items-0-id": f"{item.pk}",
                "items-0-priority": "0",
                "items-0-title": "Bla",
                "items-0-description": "Ho",
                "items-0-image": SimpleUploadedFile("my-image.png", black_pixel, content_type="image/png"),
                "items-0-image_alt_text": "aaa",
                "items-0-link": "",
                "_save": "Enregistrer",
            },
        )
        assertRedirects(response, reverse("admin:communications_announcementcampaign_changelist"))
        item.refresh_from_db()
        filename = pathlib.Path(item.image.name)
        assert uuid.UUID(filename.stem)  # Did not use the provided filename
        assert filename.suffix == ".png"
        assert File.objects.filter(deleted_at__isnull=False).count() == 1
        assert item.image_storage.deleted_at is None
        assert item.image_storage.key.startswith("news-images/")
