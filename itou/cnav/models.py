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
                    certifier=IdentityCertificationAuthorities.API_FT_RECHERCHER_USAGER,
                    jobseeker_profile=self.profile,
                    certified_at=self.last_attempt_at,
                ),
            ],
        )
        logger.info(
            "Match between profile=%s and CNAVRecord pk=%s - IdentityCertification added", self.profile.pk, self.pk
        )


# TODO:
# Ajout d'une tache huey qui prend la pk de ce modèle en entrée et qui (en prenant un lock):
#   * vérifie si il n'y a pas déjà un résultat (potentiellement vide)
#   * si c'est le cas: rien à faire et on quitte
#   * sinon:
#     - on interroge l'API de la CNAV:
#         * si soucis de communication, on met juste à jour last_attempt_at et on quitte en remettant une tache huey
#           à plus tard (raise RetryTask(delay=xxx)). Pour les 429, bien lire l'header pour suffisamment repousser
#         * si réponse de l'API:
#           - on stocke last_attempt_at et le résultat
#           - si le résultat est négatif, on recrée un autre objet avec dans input data une liste de champs plus
#             réduite pour réinterroger la CNAV (il faudra vérifier si cela est pertinent)
#
# Ajout d'une tache planifiée qui supprime les vieux objets non liés à un profile
# Ajout d'une tache planifiée qui tente de traiter les vieilles taches huey
# Modification de la fusion de deux comptes candidats pour garder ces objets
#
# Lors de la création d'un compte candidat: on crée cet objet dès que toutes les informations sont récupérées,
# on stocke la pk de cet objet dans la session et on enqueue la tache on_commit.
# A la dernière étape, si l'usager est bien créé, on rattache l'objet à l'usager (quelque soit le résultat de l'appel
# à la CNAV).
# Si:
#   - le pro a le droit de voir les infos de la CNAV
#   - la CNAV a déjà répondu à notre appel
#   - les informations ne correspondent pas exactement
# alors on affiche le tableau comparatif (à quelle étape ?) pour laisser le pro choisir quelles données qu'il
# souhaite conserver
# S'il choisit la CNAV (ou si les données correspondaient parfaitement), on rajoute sur le profile une FK cnav_infos
# qui pointe vers l'objet des données récupérées, ou alors un IdentityCertificationAuthorities
# La présence de cette clef indique que le profil de l'usager est certifié et il ne peut plus changer
# - son nom de naissance
# - son prénom (ou uniquement le changer pour un de ses prénoms ?)
# - sa date de naissance
# - son lieu de naissance
# - son sexe
