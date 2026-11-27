import logging
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from itou.cnav.enums import CNAVRecordOrigin
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import IdentityCertification, JobSeekerProfile
from itou.utils.apis.cnav import PersonalInfos


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

    def get_personal_infos(self) -> PersonalInfos | None:
        try:
            return PersonalInfos.from_dict(self.result_infos)
        except ValueError:
            logger.info("Unexpected result_infos format for CNAVRecord pk=%s", self.pk)
            return

    def try_to_certify_profile(self):
        from itou.cnav.matcher import match, update_profile_from_record

        if self.profile is None:
            return

        personal_infos = self.get_personal_infos()
        if personal_infos is None:
            return

        if not match(profile=self.profile, cnav_record=self):
            return
        update_profile_from_record(profile=self.profile, cnav_record=self)
        IdentityCertification.objects.upsert_certifications(
            [
                IdentityCertification(
                    certifier=IdentityCertificationAuthorities.API_CNAV,
                    jobseeker_profile=self.profile,
                    certified_at=self.last_attempt_at,
                ),
            ],
        )
        logger.info(
            "Match between JobSeekerProfile=%s and CNAVRecord=%s - IdentityCertification added",
            self.profile.pk,
            self.pk,
        )


# TODO:
# * Ajout d'une tache planifiée qui supprime les vieux CNAVRecord non liés à un profile
# * Ajout d'une tache planifiée qui tente de traiter les vieux CNAVRecord (a priori sans tache huey)
# * Modification de la fusion de deux comptes candidats pour garder ces objets
#
# Lors de la validation de la création de l'usager, on vérifie le CNAVRecord lié et si:
#   - le pro a le droit de voir les infos de la CNAV
#   - la CNAV a déjà répondu à notre appel
#   - les informations ne correspondent pas exactement
# alors on affiche le tableau comparatif (à quelle étape ?) pour laisser le pro choisir quelles données il
# souhaite conserver
# S'il choisit la CNAV (ou si les données correspondaient parfaitement), on aligne les infos sur le profile
# et on certifie l'usager (via IdentityCertificationAuthorities)
