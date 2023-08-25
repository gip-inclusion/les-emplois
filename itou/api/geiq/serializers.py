import os
from typing import List

from django.apps import apps
from django.db import connection, models
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

import itou.job_applications.enums as enums
from itou.asp.models import EducationLevel
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from itou.job_applications.models import JobApplication, PriorAction
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.siaes.enums import ContractType, SiaeKind
from itou.users.enums import Title


class LabelEducationLevel(models.TextChoices):
    LEVEL_3 = "LEVEL_3", "Niveau 3 (CAP, BEP)"
    LEVEL_4 = "LEVEL_4", "Niveau 4 (BP, Bac Général, Techno ou Pro, BT)"
    LEVEL_5 = "LEVEL_5", "Niveau 5 ou + (Bac+2 ou +)"
    NO_QUALIFICATION = "NO_QUALIFICATION", "Sans qualification"
    OTHER = "OTHER", "Autre"


LABEL_TO_ASP_EDUCATION_LEVELS = {
    LabelEducationLevel.NO_QUALIFICATION: [
        EducationLevel.NON_CERTIFYING_QUALICATIONS,
        EducationLevel.NO_SCHOOLING,
        EducationLevel.NO_SCHOOLING_BEYOND_MANDATORY,
        EducationLevel.TRAINING_1_YEAR,
    ],
    LabelEducationLevel.LEVEL_3: [EducationLevel.BEP_OR_CAP_DIPLOMA, EducationLevel.BEP_OR_CAP_LEVEL],
    LabelEducationLevel.LEVEL_4: [EducationLevel.BAC_LEVEL, EducationLevel.BT_OR_BACPRO_LEVEL],
    LabelEducationLevel.LEVEL_5: [
        EducationLevel.BTS_OR_DUT_LEVEL,
        EducationLevel.LICENCE_LEVEL,
        EducationLevel.THIRD_CYCLE_OR_ENGINEERING_SCHOOL,
    ],
}

ASP_TO_LABEL_EDUCATION_LEVELS = {
    asp_level: label_level for label_level, values in LABEL_TO_ASP_EDUCATION_LEVELS.items() for asp_level in values
}


def lazy_administrative_criteria_choices():
    # The CI check is only there because the `manage.py makemigrations --check` would fail otherwise.
    # Indeed, it is run before any migrations are done but in a ready context. Another way is to migrate
    # the app before that check but that would make the CI slower all the time.
    # Another way to see it is that it's reasonable that those specific API spectacular annotations are
    # not rendered on CI.
    # I would be happy to hear of another way to do it, by rendering `extend_schema_field` itself lazy maybe ?
    if apps.ready and not os.getenv("CI", False):
        try:
            connection.ensure_connection()
            return GEIQAdministrativeCriteria.objects.order_by("slug").values_list("slug", "name")
        except Exception:  # this happens during tests when pytest reads the code and has not initialized the db yet
            pass
    return [[0, "-"]]  # make spectacular happy, it needs at least one option in the choices.


class PriorActionSerializer(serializers.ModelSerializer):
    code = serializers.ChoiceField(
        source="action", choices=sorted(enums.ProfessionalSituationExperience.choices + enums.Prequalification.choices)
    )
    date_debut = serializers.DateField(source="dates.lower")
    date_fin = serializers.DateField(source="dates.upper")

    class Meta:
        model = PriorAction
        fields = (
            "code",
            "date_debut",
            "date_fin",
        )


class GeiqJobApplicationSerializer(serializers.ModelSerializer):
    id_embauche = serializers.UUIDField(source="pk")
    id_utilisateur = serializers.UUIDField(source="job_seeker.public_id")
    siret_employeur = serializers.CharField(source="to_siae.siret")
    nir = serializers.CharField(source="job_seeker.nir")
    nom = serializers.CharField(source="job_seeker.last_name")
    prenom = serializers.CharField(source="job_seeker.first_name")
    date_naissance = serializers.DateField(source="job_seeker.birthdate")
    civilite = serializers.ChoiceField(
        source="job_seeker.title",
        choices=sorted(Title.choices),
    )
    adresse_ligne_1 = serializers.CharField(source="job_seeker.address_line_1")
    adresse_ligne_2 = serializers.CharField(source="job_seeker.address_line_2")
    adresse_code_postal = serializers.CharField(source="job_seeker.post_code")
    adresse_ville = serializers.CharField(source="job_seeker.city")
    source_orientation = serializers.ChoiceField(source="sender_kind", choices=sorted(enums.SenderKind.choices))
    type_prescripteur = serializers.ChoiceField(
        source="sender_prescriber_organization.kind",
        allow_null=True,
        choices=sorted(PrescriberOrganizationKind.choices),
    )
    criteres_eligibilite = serializers.SerializerMethodField()
    auteur_diagnostic = serializers.ChoiceField(
        source="geiq_eligibility_diagnosis.author_kind",
        choices=sorted(AuthorKind.choices),
        allow_null=True,
    )
    niveau_formation = serializers.SerializerMethodField()
    mises_en_situation_pro = PriorActionSerializer(many=True)
    prequalifications = PriorActionSerializer(many=True)
    jours_accompagnement = serializers.IntegerField(source="prehiring_guidance_days", min_value=0)
    type_contrat = serializers.ChoiceField(
        source="contract_type",
        choices=ContractType.choices_for_siae_kind(SiaeKind.GEIQ),
    )
    poste_occupe = serializers.SerializerMethodField()
    duree_hebdo = serializers.IntegerField(
        source="nb_hours_per_week",
        min_value=enums.GEIQ_MIN_HOURS_PER_WEEK,
        max_value=enums.GEIQ_MAX_HOURS_PER_WEEK,
    )
    date_debut_contrat = serializers.DateField(source="hiring_start_at")
    date_fin_contrat = serializers.DateField(source="hiring_end_at")
    type_qualification = serializers.ChoiceField(
        source="qualification_type",
        allow_null=True,
        choices=sorted(enums.QualificationType.choices),
    )
    niveau_qualification = serializers.ChoiceField(
        source="qualification_level",
        allow_null=True,
        choices=sorted(enums.QualificationLevel.choices),
    )
    nb_heures_formation = serializers.IntegerField(source="planned_training_hours", min_value=0)
    est_vae_inversee = serializers.BooleanField(source="inverted_vae_contract")

    class Meta:
        model = JobApplication
        fields = (
            "id_embauche",
            "id_utilisateur",
            "siret_employeur",
            "nir",
            "nom",
            "prenom",
            "date_naissance",
            "civilite",
            "adresse_ligne_1",
            "adresse_ligne_2",
            "adresse_code_postal",
            "adresse_ville",
            "source_orientation",
            "type_prescripteur",
            "criteres_eligibilite",
            "auteur_diagnostic",
            "niveau_formation",
            "mises_en_situation_pro",
            "prequalifications",
            "jours_accompagnement",
            "type_contrat",
            "poste_occupe",
            "duree_hebdo",
            "date_debut_contrat",
            "date_fin_contrat",
            "type_qualification",
            "niveau_qualification",
            "nb_heures_formation",
            "est_vae_inversee",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=lazy_administrative_criteria_choices()))
    def get_criteres_eligibilite(self, obj) -> List[str]:
        if diag := obj.geiq_eligibility_diagnosis:
            return sorted({crit.slug for crit in diag.administrative_criteria.all()})
        return []

    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelEducationLevel.choices)))
    def get_niveau_formation(self, obj) -> str | None:
        asp_level = obj.job_seeker.jobseeker_profile.education_level
        if asp_level:
            return ASP_TO_LABEL_EDUCATION_LEVELS.get(asp_level, LabelEducationLevel.OTHER)
        return None

    def get_poste_occupe(self, obj) -> str | None:
        """
        Ce champ n'est pas encore disponible dans les Emplois de l'inclusion.

        Il sera renvoyé sous forme d'un code d'appellation métier ROME Pôle Emploi.

        Voir https://www.pole-emploi.org/opendata/repertoire-operationnel-des-meti.html?type=article
        """
        # FIXME(vperron): Integrate this when the data becomes available, cf. PR #2460.
        # For the possible values, just point towards the Pole Emploi reference.
        return None
