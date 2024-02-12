from typing import List

from django.db import models
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

import itou.job_applications.enums as enums
from itou.asp.models import EducationLevel
from itou.companies.enums import ContractType
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from itou.job_applications.models import JobApplication, PriorAction
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import Title


class LabelCivilite(models.TextChoices):
    H = "H", "Homme"
    F = "F", "Femme"


EMPLOIS_TO_LABEL_CIVILITE = {
    Title.M: LabelCivilite.H,
    Title.MME: LabelCivilite.F,
}


class LabelPrescriberKind(models.TextChoices):
    ANNONCES_PI = "ANNONCES_PI", "Annonces presse / internet"
    AUTRE = "AUTRE", "Autres"
    CAP_EMPLOI = "CAP_EMPLOI", "Cap Emploi"
    CS = "CS", "Candidature spontanée"
    CT = "CT", "Collectivité territoriale (PDI…)"
    EA = "EA", "Entreprises adhérentes"
    FORUM = "FORUM", "Forum"
    GP = "GP", "Groupement d'employeurs"
    ML = "ML", "Missions locales"
    OF = "OF", "Organisme de formation"
    PE = "PE", "Pôle Emploi"
    PLIE = "PLIE", "PLIE"
    PS = "PS", "Parrainage de salariés"
    SIAE_CONS = "SIAE_CONS", "SIAE et consors"


EMPLOIS_TO_LABEL_PRESCRIBER = {
    PrescriberOrganizationKind.CAP_EMPLOI: LabelPrescriberKind.CAP_EMPLOI,
    PrescriberOrganizationKind.ML: LabelPrescriberKind.ML,
    PrescriberOrganizationKind.ODC: LabelPrescriberKind.CT,
    PrescriberOrganizationKind.PE: LabelPrescriberKind.PE,
    PrescriberOrganizationKind.DEPT: LabelPrescriberKind.CT,
    PrescriberOrganizationKind.ASE: LabelPrescriberKind.CT,
    PrescriberOrganizationKind.PLIE: LabelPrescriberKind.PLIE,
}


def get_precision_prescripteur_choices():
    return sorted(label for _, label in PrescriberOrganizationKind.choices + enums.SenderKind.choices)


class LabelEducationLevel(models.TextChoices):
    N3 = "N3", "Niveau 3 (CAP, BEP)"
    N4 = "N4", "Niveau 4 (BP, Bac Général, Techno ou Pro, BT)"
    N5 = "N5", "Niveau 5 ou + (Bac+2 ou +)"
    SQ = "SQ", "Sans qualification"


LABEL_TO_ASP_EDUCATION_LEVELS = {
    LabelEducationLevel.SQ: [
        EducationLevel.NON_CERTIFYING_QUALICATIONS,
        EducationLevel.NO_SCHOOLING,
        EducationLevel.NO_SCHOOLING_BEYOND_MANDATORY,
        EducationLevel.TRAINING_1_YEAR,
    ],
    LabelEducationLevel.N3: [EducationLevel.BEP_OR_CAP_DIPLOMA, EducationLevel.BEP_OR_CAP_LEVEL],
    LabelEducationLevel.N4: [EducationLevel.BAC_LEVEL, EducationLevel.BT_OR_BACPRO_LEVEL],
    LabelEducationLevel.N5: [
        EducationLevel.BTS_OR_DUT_LEVEL,
        EducationLevel.LICENCE_LEVEL,
        EducationLevel.THIRD_CYCLE_OR_ENGINEERING_SCHOOL,
    ],
}

ASP_TO_LABEL_EDUCATION_LEVELS = {
    asp_level: label_level for label_level, values in LABEL_TO_ASP_EDUCATION_LEVELS.items() for asp_level in values
}


class LabelDiagAuthorKind(models.TextChoices):
    PRESCRIPTEUR = "PRESCRIPTEUR", "Prescripteur"
    EMPLOYEUR = "EMPLOYEUR", "Employeur"
    GEIQ = "GEIQ", "GEIQ"


EMPLOIS_TO_LABEL_DIAG_AUTHOR_KIND = {
    AuthorKind.PRESCRIBER: LabelDiagAuthorKind.PRESCRIPTEUR,
    AuthorKind.EMPLOYER: LabelDiagAuthorKind.EMPLOYEUR,
    AuthorKind.GEIQ: LabelDiagAuthorKind.GEIQ,
}


class LabelProfessionalSituationExperience(models.TextChoices):
    MRS = "MRS", "Mise en relation sociale"
    AUTRE = "AUTRE", "Autre"
    PMSMP = "PMSMP", "Période de mise en situation en milieu professionnel"
    STAGE = "STAGE", "Stage"


EMPLOIS_TO_LABEL_PRO_SITU_EXP = {
    enums.ProfessionalSituationExperience.MRS: LabelProfessionalSituationExperience.MRS,
    enums.ProfessionalSituationExperience.OTHER: LabelProfessionalSituationExperience.AUTRE,
    enums.ProfessionalSituationExperience.PMSMP: LabelProfessionalSituationExperience.PMSMP,
    enums.ProfessionalSituationExperience.STAGE: LabelProfessionalSituationExperience.STAGE,
}


class LabelPrequalification(models.TextChoices):
    AFPR = "AFPR", "AFPR"
    LOCAL_PLAN = "LOCAL_PLAN", "Dispositif régional ou sectoriel"
    POE = "POE", "POE"
    OTHER = "AUTRE", "Autre"


EMPLOIS_TO_LABEL_PREQUALIFICATION = {
    enums.Prequalification.AFPR: LabelPrequalification.AFPR,
    enums.Prequalification.LOCAL_PLAN: LabelPrequalification.LOCAL_PLAN,
    enums.Prequalification.POE: LabelPrequalification.POE,
    enums.Prequalification.OTHER: LabelPrequalification.OTHER,
}


class LabelContractType(models.TextChoices):
    # TODO(vperron): decide with LABEL to keep those or not.
    # For now, we do not use those codes for the GEIQ contract types.
    # CUI_F = "CUI+F", "CUI (toute catégorie)"
    # CUI = "CUI", "CUI (catégorie 1)"
    # AUTRE_F = "Autre F", "Autre F"
    # CDD_CPF = "CDD+CPF", "CDD CPF"
    # CDD_autre = "CDD+autre", "CDD autre"
    CDD = "CDD", "CDD"
    CDI = "CDI", "CDI"
    CPRO = "CPRO", "Contrat de professionnalisation"
    CAPP = "CAPP", "Contrat d'apprentissage"
    AUTRE_SF = "Autre SF", "Autre SF"


EMPLOIS_TO_LABEL_CONTRACT_TYPE = {
    ContractType.FIXED_TERM: LabelContractType.CDD,
    ContractType.PERMANENT: LabelContractType.CDI,
    ContractType.PROFESSIONAL_TRAINING: LabelContractType.CPRO,
    ContractType.APPRENTICESHIP: LabelContractType.CAPP,
    ContractType.OTHER: LabelContractType.AUTRE_SF,
}


class LabelQualificationType(models.TextChoices):
    RNCP = "RNCP", "Diplôme d’État ou Titre homologué"
    CQP = "CQP", "CQP"
    CCN = "CCN", "Positionnement de CCN"
    # TODO(vperron): decide with LABEL to keep those or not.
    # For now, we do not use those codes for the GEIQ qualification levels.
    # BLOC = "BLOC", "Bloc(s) de compétences enregistrées au RNCP"
    # OPCO = "OPCO", "Autres compétences validées par l’OPCO"


EMPLOIS_TO_LABEL_QUALIFICATION_TYPE = {
    enums.QualificationType.CCN: LabelQualificationType.CCN,
    enums.QualificationType.CQP: LabelQualificationType.CQP,
    enums.QualificationType.STATE_DIPLOMA: LabelQualificationType.RNCP,
}


EMPLOIS_TO_LABEL_QUALIFICATION_LEVEL = {
    enums.QualificationLevel.LEVEL_3: LabelEducationLevel.N3,
    enums.QualificationLevel.LEVEL_4: LabelEducationLevel.N4,
    enums.QualificationLevel.LEVEL_5: LabelEducationLevel.N5,
    enums.QualificationLevel.NOT_RELEVANT: LabelEducationLevel.SQ,
}


def lazy_administrative_criteria_choices():
    return dict(GEIQAdministrativeCriteria.objects.order_by("name").values_list("api_code", "name"))


class LazyChoiceField(serializers.ChoiceField):
    def get_choices(self):
        if callable(self._choices):
            self._choices = self._choices()
        return self._choices

    def set_choices(self, choices):
        self._choices = choices

    choices = property(fget=get_choices, fset=set_choices)


class BasePriorActionSerializer(serializers.ModelSerializer):
    code = serializers.SerializerMethodField()
    date_debut = serializers.DateField(source="dates.lower")
    date_fin = serializers.DateField(source="dates.upper")

    class Meta:
        model = PriorAction
        fields = (
            "code",
            "date_debut",
            "date_fin",
        )


class MSPPriorActionSerializer(BasePriorActionSerializer):
    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelProfessionalSituationExperience.choices)))
    def get_code(self, obj) -> str:
        return EMPLOIS_TO_LABEL_PRO_SITU_EXP[obj.action]


class PrequalPriorActionSerializer(BasePriorActionSerializer):
    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelPrequalification.choices)))
    def get_code(self, obj) -> str:
        return EMPLOIS_TO_LABEL_PREQUALIFICATION[obj.action]


class GeiqJobApplicationSerializer(serializers.ModelSerializer):
    id_embauche = serializers.UUIDField(source="pk")
    id_utilisateur = serializers.UUIDField(source="job_seeker.public_id")
    siret_employeur = serializers.CharField(source="to_company.siret")
    nom = serializers.CharField(source="job_seeker.last_name")
    prenom = serializers.CharField(source="job_seeker.first_name")
    date_naissance = serializers.DateField(source="job_seeker.birthdate")
    civilite = serializers.SerializerMethodField()
    adresse_ligne_1 = serializers.CharField(source="job_seeker.address_line_1")
    adresse_ligne_2 = serializers.CharField(source="job_seeker.address_line_2")
    adresse_code_postal = serializers.CharField(source="job_seeker.post_code")
    adresse_ville = serializers.CharField(source="job_seeker.city")
    prescripteur_origine = serializers.SerializerMethodField()
    precision_prescripteur = serializers.SerializerMethodField()
    criteres_eligibilite = serializers.SerializerMethodField()
    auteur_diagnostic = serializers.SerializerMethodField()
    niveau_formation = serializers.SerializerMethodField()
    mises_en_situation_pro = MSPPriorActionSerializer(many=True)
    prequalifications = PrequalPriorActionSerializer(many=True)
    jours_accompagnement = serializers.IntegerField(source="prehiring_guidance_days", min_value=0)
    type_contrat = serializers.SerializerMethodField()
    poste_occupe = serializers.SerializerMethodField()
    duree_hebdo = serializers.IntegerField(
        source="nb_hours_per_week",
        min_value=enums.GEIQ_MIN_HOURS_PER_WEEK,
        max_value=enums.GEIQ_MAX_HOURS_PER_WEEK,
    )
    date_debut_contrat = serializers.DateField(source="hiring_start_at")
    date_fin_contrat = serializers.DateField(source="hiring_end_at")
    type_qualification = serializers.SerializerMethodField()
    niveau_qualification = serializers.SerializerMethodField()
    nb_heures_formation = serializers.IntegerField(source="planned_training_hours", min_value=0)
    est_vae_inversee = serializers.BooleanField(source="inverted_vae_contract")

    class Meta:
        model = JobApplication
        fields = (
            "id_embauche",
            "id_utilisateur",
            "siret_employeur",
            "nom",
            "prenom",
            "date_naissance",
            "civilite",
            "adresse_ligne_1",
            "adresse_ligne_2",
            "adresse_code_postal",
            "adresse_ville",
            "prescripteur_origine",
            "precision_prescripteur",
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

    @extend_schema_field(LazyChoiceField(choices=lazy_administrative_criteria_choices))
    def get_criteres_eligibilite(self, obj) -> List[str]:
        if diag := obj.geiq_eligibility_diagnosis:
            return sorted({crit.api_code for crit in diag.administrative_criteria.all()})
        return []

    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelCivilite.choices)))
    def get_civilite(self, obj) -> str | None:
        return EMPLOIS_TO_LABEL_CIVILITE.get(obj.job_seeker.title, None)

    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelPrescriberKind.choices)))
    def get_prescripteur_origine(self, obj) -> str | None:
        if org := getattr(obj, "sender_prescriber_organization", None):
            return EMPLOIS_TO_LABEL_PRESCRIBER.get(org.kind, LabelPrescriberKind.AUTRE)
        return LabelPrescriberKind.AUTRE

    @extend_schema_field(serializers.ChoiceField(choices=get_precision_prescripteur_choices()))
    def get_precision_prescripteur(self, obj) -> str | None:
        if org := getattr(obj, "sender_prescriber_organization", None):
            return PrescriberOrganizationKind(org.kind).label
        return enums.SenderKind(obj.sender_kind).label

    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelDiagAuthorKind.choices)))
    def get_auteur_diagnostic(self, obj) -> str | None:
        if diag := obj.geiq_eligibility_diagnosis:
            return EMPLOIS_TO_LABEL_DIAG_AUTHOR_KIND[diag.author_kind]
        return None

    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelEducationLevel.choices)))
    def get_niveau_formation(self, obj) -> str | None:
        asp_level = obj.job_seeker.jobseeker_profile.education_level
        if asp_level:
            return ASP_TO_LABEL_EDUCATION_LEVELS[asp_level]
        return None

    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelContractType.choices)))
    def get_type_contrat(self, obj) -> str | None:
        return EMPLOIS_TO_LABEL_CONTRACT_TYPE.get(obj.contract_type, None)

    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelQualificationType.choices)))
    def get_type_qualification(self, obj) -> str | None:
        return EMPLOIS_TO_LABEL_QUALIFICATION_TYPE.get(obj.qualification_type, None)

    @extend_schema_field(serializers.ChoiceField(choices=sorted(LabelEducationLevel.choices)))
    def get_niveau_qualification(self, obj) -> str | None:
        return EMPLOIS_TO_LABEL_QUALIFICATION_LEVEL.get(obj.qualification_level, None)

    def get_poste_occupe(self, obj) -> str | None:
        """
        Ce champ n'est pas encore disponible dans les Emplois de l'inclusion.

        Il sera renvoyé sous forme d'un code d'appellation métier ROME Pôle Emploi.

        Voir https://www.pole-emploi.org/opendata/repertoire-operationnel-des-meti.html?type=article
        """
        # FIXME(vperron): Integrate this when the data becomes available, cf. PR #2460.
        # For the possible values, just point towards the Pole Emploi reference.
        return None
