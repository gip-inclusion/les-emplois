import contextlib
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


def _matching_infos_for_profile(profile: JobSeekerProfile):
    return {
        "nir": profile.nir,
        "last_name": profile.user.last_name.casefold(),
        "first_name": profile.user.first_name.casefold(),
        "birthdate": profile.birthdate,
        "title": profile.user.title,
        "birth_insee_code": profile.birth_insee_code(),
    }


def _matching_infos_for_record(cnav_record: CNAVRecord):
    personal_infos = cnav_record.get_personal_infos()
    if personal_infos is None:
        return {}
    birthdate = None
    if personal_infos.birth_date is not None:
        with contextlib.suppress(ValueError):
            birthdate = datetime.date.fromisoformat(personal_infos.birth_date)
    return {
        "nir": {personal_infos.number} | set(personal_infos.number_history),
        "last_name": _extract_known_case_folded_last_names(personal_infos),
        "first_name": _extract_known_case_folded_first_names(personal_infos),
        "birthdate": birthdate,
        "birth_insee_code": personal_infos.birth_place,
    }


def match(*, profile: JobSeekerProfile, cnav_record: CNAVRecord):
    profile_matching_infos = _matching_infos_for_profile(profile)
    record_matching_infos = _matching_infos_for_record(cnav_record)
    if not profile_matching_infos or not record_matching_infos:
        return False
    mismatched_fields = []
    for field in ["nir", "last_name", "first_name", "birth_date", "birth_insee_code"]:
        profile_value = profile_matching_infos.get(field)
        record_value = record_matching_infos.get(field)
        if not profile_matching_infos or not record_value:
            # Ignoring empty fields
            continue
        if isinstance(record_value, set):
            if profile_value not in record_value:
                mismatched_fields.append(field)
        else:
            if profile_value != record_value:
                mismatched_fields.append(field)
    if mismatched_fields:
        logger.info(
            "Mismatch between JobSeekerProfile=%s and CNAVRecord=%s on fields: %s",
            profile.pk,
            cnav_record.pk,
            mismatched_fields,
        )
        return False
    return True


def record_to_profile_values(cnav_record: CNAVRecord):
    values = {}

    personal_infos = cnav_record.get_personal_infos()
    if personal_infos is None:
        return values

    values["nir"] = personal_infos.number

    if personal_infos.sex_code:
        values["title"] = {1: Title.M, 2: Title.MME}.get(personal_infos.sex_code)

    if personal_infos.birth_date:
        with contextlib.suppress(ValueError):
            values["birthdate"] = datetime.date.fromisoformat(personal_infos.birth_date)

    if insee_code := personal_infos.birth_place:
        if insee_code.startswith("99"):
            values["birth_country"] = Country.objects.get(code=insee_code[2:])
            values["birth_place"] = None
        else:
            commune = Commune.objects.filter(code=insee_code).first()
            if commune:
                values["birth_place"] = commune
                values["birth_country_id"] = Country.FRANCE_ID
            else:
                values["birth_country"] = Country.objects.get(code=insee_code[2:], group=Country.Group.FRANCE)
                values["birth_place"] = None

    # last_name/first_name are ignored for now: if a match was found it means that the data are okayish
    return values


def update_profile_from_record(*, profile, cnav_record):
    record_infos = record_to_profile_values(cnav_record)

    if (record_title := record_infos.pop("title", None)) is not None and profile.user.title != record_title:
        profile.user.title = record_title
        profile.user.save(update_fields={"title"})

    update_fields = set()
    for field, value in record_infos.items():
        if value != getattr(profile, field):
            setattr(profile, field, value)
            update_fields.add(field)
    if update_fields:
        profile.save(update_fields=update_fields)


class CNAVRecord(models.Model):
    uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    origin = models.CharField(choices=CNAVRecordOrigin.choices)

    profile = models.ForeignKey(JobSeekerProfile, null=True, on_delete=models.SET_NULL, related_name="cnav_records")
    input_data = models.JSONField(encoder=DjangoJSONEncoder)
    result = models.JSONField(encoder=DjangoJSONEncoder, null=True)

    last_attempt_at = models.DateTimeField(null=True)
    next_attempt_at = models.DateTimeField(null=True)

    def get_personal_infos(self) -> PersonalInfos | None:
        try:
            interops_result = InterOpsResult.from_dict(self.result)
        except ValueError:
            logger.info("Unexpected result format for CNAVRecord pk=%s", self.pk)
            return
        return interops_result.infos

    def try_to_certify_profile(self):
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
