import re

from rest_framework import serializers
from unidecode import unidecode

from itou.asp.models import AllocationDuration, EducationLevel, EITIContributions, LaneExtension, LaneType, SiaeMeasure
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification
from itou.employee_record.typing import CodeComInsee
from itou.users.enums import Title
from itou.users.models import User
from itou.utils.serializers import DefaultIfEmptyChoiceField, NullField, NullIfEmptyCharField, NullIfEmptyChoiceField


class _PersonSerializer(serializers.Serializer):
    passIae = serializers.CharField(source="approval_number")  # Required
    idItou = serializers.CharField(source="job_application.job_seeker.jobseeker_profile.asp_uid")  # Required

    civilite = serializers.SerializerMethodField()  # Required
    nomUsage = serializers.SerializerMethodField()  # Required
    nomNaissance = NullField()  # Optional
    prenom = serializers.SerializerMethodField()  # Required
    dateNaissance = serializers.DateField(
        format="%d/%m/%Y", source="job_application.job_seeker.jobseeker_profile.birthdate"
    )  # Required

    codeComInsee = serializers.SerializerMethodField()  # Required if the birth country is France
    codeInseePays = serializers.CharField(
        source="job_application.job_seeker.jobseeker_profile.birth_country.code"
    )  # Required
    codeGroupePays = serializers.CharField(
        source="job_application.job_seeker.jobseeker_profile.birth_country.group"
    )  # Required

    passDateDeb = serializers.DateField(format="%d/%m/%Y", source="job_application.approval.start_at")  # Required
    passDateFin = serializers.DateField(format="%d/%m/%Y", source="job_application.approval.end_at")  # Required

    # TODO: Remove to fields after confirmation as they are not mentioned in CC V1.05, § 2.4.1
    sufPassIae = NullField()
    codeDpt = serializers.CharField(source="job_application.job_seeker.birth_place.department_code", required=False)

    def get_civilite(self, obj: EmployeeRecord) -> str | None:
        if title := obj.job_application.job_seeker.title:
            return title
        if nir := obj.job_application.job_seeker.jobseeker_profile.nir:
            return Title.M if nir[0] == 1 else Title.MME
        return None

    def get_nomUsage(self, obj: EmployeeRecord) -> str:
        return unidecode(obj.job_application.job_seeker.last_name).upper()

    def get_prenom(self, obj: EmployeeRecord) -> str:
        # ASP limits first names to 30 chars
        first_names = unidecode(obj.job_application.job_seeker.first_name).upper()
        if len(first_names) > 30:
            return first_names[:30].rsplit(" ", 1)[0]
        return first_names

    def get_codeComInsee(self, obj: EmployeeRecord) -> CodeComInsee:
        # Another ASP subtlety, making top-level and children with the same name
        # The commune can be empty if the job seeker is not born in France
        if birth_place := obj.job_application.job_seeker.jobseeker_profile.birth_place:
            return {
                "codeComInsee": birth_place.code,
                "codeDpt": birth_place.department_code,
            }

        # However, if the employee is not born in France
        # the department code must be '099' (error 3411)
        return {
            "codeComInsee": None,
            "codeDpt": "099",
        }


class _StaticPersonSerializer(_PersonSerializer):
    """Force the birth country to Iceland to bypass ASP checks for update notifications"""

    codeComInsee = serializers.ReadOnlyField(
        default={"codeComInsee": None, "codeDpt": "099"}
    )  # Required if the birth country is France
    codeInseePays = serializers.ReadOnlyField(default="102")  # Required.
    codeGroupePays = serializers.ReadOnlyField(default="3")  # Required

    def get_civilite(self, obj: EmployeeRecord) -> str:
        return super().get_civilite(obj) or Title.M.value


class _AddressSerializer(serializers.Serializer):
    # Source object is a job seeker

    adrTelephone = NullField()  # Optional
    adrMail = NullField()  # Optional

    adrNumeroVoie = NullIfEmptyCharField(source="jobseeker_profile.hexa_lane_number", allow_blank=True)  # Optional
    codeextensionvoie = NullIfEmptyChoiceField(
        choices=LaneExtension.choices, source="jobseeker_profile.hexa_std_extension", allow_blank=True
    )  # Optional
    codetypevoie = serializers.ChoiceField(
        choices=LaneType.choices, source="jobseeker_profile.hexa_lane_type"
    )  # Required
    adrLibelleVoie = serializers.SerializerMethodField()  # Required
    adrCpltDistribution = serializers.SerializerMethodField()  # Optional

    codeinseecom = serializers.CharField(source="jobseeker_profile.hexa_commune.code")  # Required
    codepostalcedex = serializers.CharField(source="jobseeker_profile.hexa_post_code")  # Required

    def get_adrLibelleVoie(self, obj: User) -> str | None:
        # Remove diacritics and parenthesis from adrLibelleVoie field fixes ASP error 3330
        # (parenthesis are not described as invalid characters in specification document).
        lane = obj.jobseeker_profile.hexa_lane_name
        if lane:
            return unidecode(lane.translate({ord(ch): "" for ch in "()"}))
        return ""

    def get_adrCpltDistribution(self, obj: User) -> str | None:
        # Don't send extended address if it must be truncated:
        # Do not lower quality of data on 'itou' side
        # Check ASP rule : T030_c026_rg002
        # This rule is badly written, and inaccurate (regarding special characters).
        # Follows the acceptable format / RE for this field (now validated by ASP).
        additional_address = obj.jobseeker_profile.hexa_additional_address
        if not additional_address:
            # Force empty string to be rendered as `null`
            return None
        if additional_address and not re.match("^[a-zA-Z0-9@ ]{,32}$", additional_address):
            return None
        return additional_address


class _StaticAddressSerializer(_AddressSerializer):
    """Use the France Travail agency address to bypass ASP checks for update notifications"""

    adrNumeroVoie = serializers.ReadOnlyField(default="3")  # Optional
    codeextensionvoie = serializers.ReadOnlyField(default=None)  # Optional
    codetypevoie = serializers.ReadOnlyField(default="AV")  # Required
    adrLibelleVoie = serializers.ReadOnlyField(default="DE BLIDA")  # Required
    adrCpltDistribution = serializers.ReadOnlyField(default=None)  # Optional

    codeinseecom = serializers.ReadOnlyField(default="57463")  # Required
    codepostalcedex = serializers.ReadOnlyField(default="57000")  # Required


class _SituationSerializer(serializers.Serializer):
    orienteur = serializers.CharField(source="asp_prescriber_type")  # Required
    niveauFormation = NullIfEmptyChoiceField(
        choices=EducationLevel.choices, source="job_application.job_seeker.jobseeker_profile.education_level"
    )  # Required

    salarieEnEmploi = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.is_employed"
    )  # Required
    salarieTypeEmployeur = serializers.CharField(source="asp_employer_type", required=False)  # Required if employed
    salarieSansEmploiDepuis = NullIfEmptyChoiceField(
        choices=AllocationDuration.choices, source="job_application.job_seeker.jobseeker_profile.unemployed_since"
    )  # Required
    salarieSansRessource = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.resourceless"
    )  # Required

    inscritPoleEmploi = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.pole_emploi_id"
    )  # Required
    inscritPoleEmploiDepuis = NullIfEmptyChoiceField(
        choices=AllocationDuration.choices, source="job_application.job_seeker.jobseeker_profile.pole_emploi_since"
    )  # Required if registered with France Travail
    numeroIDE = NullIfEmptyCharField(
        source="job_application.job_seeker.jobseeker_profile.pole_emploi_id",
        max_length=11,
    )  # Required if registered with France Travail

    salarieRQTH = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.rqth_employee"
    )  # Required
    salarieOETH = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.oeth_employee"
    )  # Required
    salarieAideSociale = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_social_allowance"
    )  # Required

    salarieBenefRSA = serializers.CharField(
        source="job_application.job_seeker.jobseeker_profile.has_rsa_allocation"
    )  # Required
    salarieBenefRSADepuis = NullIfEmptyChoiceField(
        choices=AllocationDuration.choices,
        source="job_application.job_seeker.jobseeker_profile.rsa_allocation_since",
    )  # Required if he has RSA allocation

    salarieBenefASS = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_ass_allocation"
    )  # Required
    salarieBenefASSDepuis = NullIfEmptyChoiceField(
        choices=AllocationDuration.choices,
        source="job_application.job_seeker.jobseeker_profile.ass_allocation_since",
    )  # Required if he has ASS allocation

    salarieBenefAAH = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_aah_allocation"
    )  # Required
    salarieBenefAAHDepuis = NullIfEmptyChoiceField(
        choices=AllocationDuration.choices,
        source="job_application.job_seeker.jobseeker_profile.aah_allocation_since",
    )  # Required if he has AAH allocation

    # ATA fields are outdated and have not been displayed or filled since a7fb1cb36bb942d660bf082ac22ed2367320a1f9
    salarieBenefATA = serializers.ReadOnlyField(default=False)  # Required
    salarieBenefATADepuis = serializers.ReadOnlyField(default=None)  # Required if he has ATA allocation

    salarieBenefARE = NullField()  # Required for EITI, "null" for others
    salarieBenefAREDepuis = NullField()  # Required for EITI, "null" for others
    salarieBenefPrimeActivite = NullField()  # Required for EITI, "null" for others
    salarieBenefPrimeActiviteDepuis = NullField()  # Required for EITI, "null" for others
    salarieBenefCAPE = NullField()  # Required for EITI, "null" for others
    salarieBenefCESA = NullField()  # Required for EITI, "null" for others
    nomActeurCreationEntr = NullField()  # Required for EITI, "null" for others
    revenuMensuelMoyenTI = NullField()  # Required for EITI, "null" for others
    cotisationsTI = NullField()  # Required for EITI, "null" for others


class _SituationForEITISerializer(_SituationSerializer):
    salarieOETH = serializers.ReadOnlyField(default=False)  # Always "false" for EITI

    salarieBenefARE = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_are_allocation"
    )  # Required for EITI
    salarieBenefAREDepuis = NullIfEmptyChoiceField(
        choices=AllocationDuration.choices,
        source="job_application.job_seeker.jobseeker_profile.are_allocation_since",
    )  # Required for EITI if he has ARE allocation

    salarieBenefPrimeActivite = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_activity_bonus"
    )  # Required for EITI
    salarieBenefPrimeActiviteDepuis = NullIfEmptyChoiceField(
        choices=AllocationDuration.choices,
        source="job_application.job_seeker.jobseeker_profile.activity_bonus_since",
    )  # Required for EITI if he has activity bonus

    salarieBenefCAPE = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.cape_freelance"
    )  # Required for EITI

    salarieBenefCESA = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.cesa_freelance"
    )  # Required for EITI

    nomActeurCreationEntr = serializers.SerializerMethodField()  # Required

    revenuMensuelMoyenTI = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        localize=True,
        source="job_application.job_seeker.jobseeker_profile.mean_monthly_income_before_process",
    )  # Required for EITI

    cotisationsTI = DefaultIfEmptyChoiceField(
        choices=EITIContributions.choices,
        default=EITIContributions.UNDETERMINED,
        source="job_application.job_seeker.jobseeker_profile.eiti_contributions",
    )  # Required for EITI

    def get_nomActeurCreationEntr(self, obj: EmployeeRecord) -> str:
        value = unidecode(obj.job_application.job_seeker.jobseeker_profile.actor_met_for_business_creation).upper()
        if len(value) > 100:
            return value[:100].rsplit(" ", 1)[0]
        return value


class _StaticSituationSerializer(_SituationSerializer):
    niveauFormation = serializers.ReadOnlyField(default=EducationLevel.NON_CERTIFYING_QUALICATIONS.value)  # Required

    inscritPoleEmploi = serializers.ReadOnlyField(default=False)  # Required
    inscritPoleEmploiDepuis = NullField()  # Required if registered with France Travail
    numeroIDE = NullField()  # Required if registered with France Travail


class _StaticSituationForEITISerializer(_SituationForEITISerializer):
    niveauFormation = serializers.ReadOnlyField(default=EducationLevel.NON_CERTIFYING_QUALICATIONS.value)  # Required

    inscritPoleEmploi = serializers.ReadOnlyField(default=False)  # Required
    inscritPoleEmploiDepuis = NullField()  # Required if registered with France Travail
    numeroIDE = NullField()  # Required if registered with France Travail

    revenuMensuelMoyenTI = serializers.ReadOnlyField(default="0,0")  # Required for EITI
    nomActeurCreationEntr = serializers.ReadOnlyField(default="INCONNU")  # Required for EITI


class EmployeeRecordSerializer(serializers.Serializer):
    numLigne = serializers.IntegerField(source="asp_batch_line_number")  # Required
    typeMouvement = serializers.CharField(source="ASP_MOVEMENT_TYPE")  # Required
    siret = serializers.CharField()  # Required
    mesure = serializers.CharField(source="asp_siae_type")  # Required

    # See : http://www.tomchristie.com/rest-framework-2-docs/api-guide/fields
    personnePhysique = _PersonSerializer(source="*")  # Required
    adresse = _AddressSerializer(source="job_application.job_seeker")  # Required
    situationSalarie = serializers.SerializerMethodField()  # Required

    # These fields are null at the beginning of the ASP processing
    codeTraitement = serializers.CharField(source="asp_processing_code", allow_blank=True, allow_null=True)
    libelleTraitement = serializers.CharField(source="asp_processing_label", allow_blank=True, allow_null=True)

    def get_situationSalarie(self, obj: EmployeeRecord):
        serializer_class = (
            _SituationForEITISerializer if obj.asp_siae_type is SiaeMeasure.EITI else _SituationSerializer
        )
        return serializer_class(obj).data


class EmployeeRecordUpdateNotificationSerializer(serializers.Serializer):
    numLigne = serializers.IntegerField(source="asp_batch_line_number")  # Required
    typeMouvement = serializers.CharField(source="ASP_MOVEMENT_TYPE")  # Required
    mesure = serializers.CharField(source="employee_record.asp_siae_type")  # Required
    siret = serializers.CharField(source="employee_record.siret")  # Required

    personnePhysique = serializers.SerializerMethodField()  # Required
    adresse = serializers.SerializerMethodField()  # Required
    situationSalarie = serializers.SerializerMethodField()  # Required

    # These fields are null at the beginning of the ASP processing
    codeTraitement = serializers.CharField(source="asp_processing_code", allow_blank=True, allow_null=True)
    libelleTraitement = serializers.CharField(source="asp_processing_label", allow_blank=True, allow_null=True)

    def get_personnePhysique(self, obj: EmployeeRecordUpdateNotification):
        is_missing_required_fields = not all(
            [
                getattr(obj.employee_record.job_application.job_seeker.jobseeker_profile, field)
                for field in {"birth_country", "birth_place"}
            ]
        )
        if is_missing_required_fields:
            return _StaticPersonSerializer(obj.employee_record).data
        return _PersonSerializer(obj.employee_record).data

    def get_adresse(self, obj: EmployeeRecordUpdateNotification):
        is_missing_required_fields = not all(
            [
                getattr(obj.employee_record.job_application.job_seeker.jobseeker_profile, field)
                for field in {"hexa_lane_type", "hexa_lane_name", "hexa_post_code", "hexa_commune"}
            ]
        )
        if is_missing_required_fields:
            return _StaticAddressSerializer(obj.employee_record.job_application.job_seeker).data
        return _AddressSerializer(obj.employee_record.job_application.job_seeker).data

    def get_situationSalarie(self, obj: EmployeeRecordUpdateNotification):
        is_eiti = obj.employee_record.asp_siae_type is SiaeMeasure.EITI

        required_fields = {"education_level"}
        if obj.employee_record.job_application.job_seeker.jobseeker_profile.pole_emploi_id:
            required_fields.add("pole_emploi_since")
        if is_eiti:
            required_fields.update({"mean_monthly_income_before_process", "actor_met_for_business_creation"})
        is_missing_required_fields = not all(
            [
                getattr(obj.employee_record.job_application.job_seeker.jobseeker_profile, field)
                for field in required_fields
            ]
        )

        if is_missing_required_fields:
            serializer_class = _StaticSituationForEITISerializer if is_eiti else _StaticSituationSerializer
        else:
            serializer_class = _SituationForEITISerializer if is_eiti else _SituationSerializer
        return serializer_class(obj.employee_record).data


class EmployeeRecordBatchSerializer(serializers.Serializer):
    msgInformatif = serializers.CharField(source="message", allow_blank=True, allow_null=True)  # Optional
    telId = serializers.CharField(source="id", allow_blank=True, allow_null=True)  # Optional
    lignesTelechargement = EmployeeRecordSerializer(many=True, source="elements")  # Required


class EmployeeRecordUpdateNotificationBatchSerializer(EmployeeRecordBatchSerializer):
    lignesTelechargement = EmployeeRecordUpdateNotificationSerializer(many=True, source="elements")  # Required
