import logging
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from itou.cnav.enums import CNAVRecordOrigin
from itou.users.models import JobSeekerProfile


logger = logging.getLogger(__name__)


class CNAVRecord(models.Model):
    uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    origin = models.CharField(choices=CNAVRecordOrigin.choices)

    profile = models.ForeignKey(JobSeekerProfile, null=True, on_delete=models.SET_NULL, related_name="cnav_records")

    # Input data
    input_nir = models.CharField(verbose_name="NIR recherché", max_length=15)
    input_title = models.CharField()
    input_last_name = models.CharField()
    input_first_name = models.CharField()
    input_birthdate = models.DateField()

    # Result
    result_code = models.CharField()
    result_label = models.CharField()
    result_infos = models.JSONField(encoder=DjangoJSONEncoder, null=True)

    last_attempt_at = models.DateTimeField(null=True)
    next_attempt_at = models.DateTimeField(null=True)
