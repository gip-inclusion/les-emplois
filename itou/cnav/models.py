import datetime
import logging
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from itou.asp.models import Commune, Country
from itou.cnav.enums import CNAVRecordOrigin
from itou.users.enums import IdentityCertificationAuthorities, Title
from itou.users.models import IdentityCertification, JobSeekerProfile
from itou.utils.apis.cnav import InterOpsResult, PersonalInfos


logger = logging.getLogger(__name__)


def _extract_known_case_folded_first_names(infos: PersonalInfos) -> set[str]:
    known_first_names = set()
    if infos.first_names:
        for filtered_first_name in infos.first_names.filtered:
            known_first_names.add(filtered_first_name.casefold())
        for accented_first_name in infos.first_names.accented:
            known_first_names.add(accented_first_name.casefold())
    return known_first_names


def _extract_known_case_folded_last_names(infos: PersonalInfos) -> set[str]:
    known_last_names = set()
    for name_field in ["birth_name", "common_name", "marital_name"]:
        if name := getattr(infos, name_field):
            if name.filtered:
                known_last_names.add(name.filtered.casefold())
            if name.accented:
                known_last_names.add(name.accented.casefold())
    return known_last_names


class CNAVRecord(models.Model):
    uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    origin = models.CharField(choices=CNAVRecordOrigin.choices)

    # Input infos
    profile = models.ForeignKey(JobSeekerProfile, null=True, on_delete=models.SET_NULL, related_name="cnav_records")

    input_data = models.JSONField(encoder=DjangoJSONEncoder)
    result = models.JSONField(encoder=DjangoJSONEncoder, null=True)

    last_attempt_at = models.DateTimeField(null=True)
    next_attempt_at = models.DateTimeField(null=True)

    def try_to_certify_profile(self):
        if self.profile is None:
            return
        try:
            interops_result = InterOpsResult.from_dict(self.result)
        except ValueError:
            logger.info("Unexpected result format for CNAVRecord pk=%s", self.pk)
            return
        if not interops_result.infos:
            logger.info("Empty result for CNAVRecord pk=%s", self.pk)
            return

        # The NIR is mandatory
        if self.profile.nir is None or self.profile.nir[:13] != interops_result.infos.number:
            logger.info("NIR mismatch between profile=%s and CNAVRecord pk=%s", self.profile.pk, self.pk)
            return

        if self.profile.birthdate and self.profile.birthdate.isoformat() != interops_result.infos.birth_date:
            logger.info("birth date mismatch between profile=%s and CNAVRecord pk=%s", self.profile.pk, self.pk)
            return
        if self.profile.user.title and self.profile.user.title != {1: Title.M, 2: Title.MME}.get(
            interops_result.infos.sex_code
        ):
            logger.info("title/sex_code mismatch between profile=%s and CNAVRecord pk=%s", self.profile.pk, self.pk)
            return
        if self.profile.birth_country_id and self.profile.birth_insee_code() != interops_result.infos.birth_place:
            logger.info("birth place mismatch between profile=%s and CNAVRecord pk=%s", self.profile.pk, self.pk)
            return
        if (
            self.profile.user.first_name
            and self.profile.user.first_name.casefold()
            not in _extract_known_case_folded_first_names(interops_result.infos)
        ):
            logger.info("first name mismatch between profile=%s and CNAVRecord pk=%s", self.profile.pk, self.pk)
            return
        # TODO: handle birth_name (with fallback on last_name if birth_name is empty)
        if (
            self.profile.user.last_name
            and self.profile.user.last_name.casefold()
            not in _extract_known_case_folded_last_names(interops_result.infos)
        ):
            logger.info("last name mismatch between profile=%s and CNAVRecord pk=%s", self.profile.pk, self.pk)

            return
        # If we end up here, it means that the profile and interops information are consistent
        # Let's certify!
        # First fill missing fields:
        update_fields = set()
        if not self.profile.birthdate:
            self.profile.birthdate = datetime.date.fromisoformat(interops_result.infos.birth_date)
            update_fields.add("birthdate")
        if not self.profile.birth_country_id:
            insee_code = interops_result.infos.birth_place
            if insee_code.startswith("99"):
                self.profile.birth_country = Country.objects.get(code=insee_code[2:])
                update_fields.add("birth_country")
            else:
                commune = Commune.objects.filter(code=insee_code).first()
                if commune:
                    self.profile.birth_place = commune
                    self.profile.birth_country_id = Country.FRANCE_ID
                    update_fields.add("birth_country", "birth_place")
                else:
                    self.profile.birth_country = Country.objects.get(code=insee_code[2:], group=Country.Group.FRANCE)
                    update_fields.add("birth_country")
        if update_fields:
            self.profile.save(update_fields=update_fields)

        # TODO: handle title/first_name/last_name/birth_name

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
            "Match between profile=%s and CNAVRecord pk=%s - IdentityCertification added", self.profile.pk, self.pk
        )


# TODO:
# * Ajout d'une tache planifiée qui supprime les vieux CNAVRecord non liés à un profile
# * Ajout d'une tache planifiée qui tente de traiter les vieux CNAVRecord (a priori sans tache huey)
# * Modification de la fusion de deux comptes candidats pour garder ces objets
# * Affichage du badge de certification CNAV
#
# Lors de la validation de la création de l'usager, on vérifie le CNAVRecord lié et si:
#   - le pro a le droit de voir les infos de la CNAV
#   - la CNAV a déjà répondu à notre appel
#   - les informations ne correspondent pas exactement
# alors on affiche le tableau comparatif (à quelle étape ?) pour laisser le pro choisir quelles données il
# souhaite conserver
# S'il choisit la CNAV (ou si les données correspondaient parfaitement), on aligne les infos sur le profile
# et on certifie l'usager (via IdentityCertificationAuthorities)
