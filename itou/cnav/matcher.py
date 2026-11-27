import contextlib
import datetime
import logging

from itou.asp.models import Commune, Country
from itou.cnav.models import CNAVRecord
from itou.users.enums import Title
from itou.users.models import JobSeekerProfile
from itou.utils.apis.cnav import PersonalInfos


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
        "nir": profile.nir[:13],
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
    # XXX: should we recheck the input data ?
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
