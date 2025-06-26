import io
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

    def test_add_image(self, admin_client, black_pixel, mocker):
        mocker.patch(
            "itou.files.models.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        )
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
        assert File.objects.count() == 1
        campaign = AnnouncementCampaign.objects.get()
        [item] = campaign.items.all()
        assert item.image.name == "news-images/11111111-1111-1111-1111-111111111111.png"
        assert item.image_storage.key == "news-images/11111111-1111-1111-1111-111111111111.png"

    def test_change_image(self, admin_client, black_pixel, mocker):
        # Create item before patching File.anonymized_filename's uuid,
        # otherwise Django will consider the name already exists and will append a uuid to
        # the original name.
        item = AnnouncementItemFactory(with_image=True)
        mocker.patch(
            "itou.files.models.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        )
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
        assert item.image.name == "news-images/11111111-1111-1111-1111-111111111111.png"
        assert File.objects.filter(deleted_at__isnull=False).count() == 1
        assert item.image_storage.deleted_at is None
        assert item.image_storage.key == "news-images/11111111-1111-1111-1111-111111111111.png"
