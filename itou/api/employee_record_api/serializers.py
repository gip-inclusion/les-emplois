import re

from rest_framework import serializers
from unidecode import unidecode

from itou.employee_record.models import EmployeeRecord
from itou.employee_record.typing import CodeComInsee
from itou.users.enums import Title
from itou.users.models import User
from itou.utils.serializers import NullField, NullIfEmptyCharField


# Employee record serializers are mostly the same as the ones used
# for serialization transfers, except some fields are "unobfuscated"
# and added for third-party software connecting to the API.
# For now, we are going to duplicate everything:
#   - We want to make some changes when serializing for transfer but not break the API
#   - We could then remove some transfert specific formatting rules
#   - We rarely ever touch those, so probably not too PITA to maintain, and we can refactor later


class _API_AddressSerializer(serializers.Serializer):
    """
    This class in only useful for compatibility.
    We decided not to send phone and email (business concerns and bad ASP address filters).
    But we make it available in the API for compatibility with original document
    (these fields should really be actual data, not fake, by implicit contract).
    """

    adrTelephone = serializers.CharField(source="phone")
    adrMail = serializers.CharField(source="email")

    adrNumeroVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_number")
    codeextensionvoie = NullIfEmptyCharField(source="jobseeker_profile.hexa_std_extension", allow_blank=True)
    codetypevoie = serializers.CharField(source="jobseeker_profile.hexa_lane_type")

    adrLibelleVoie = serializers.SerializerMethodField()
    adrCpltDistribution = serializers.SerializerMethodField()

    codeinseecom = serializers.CharField(source="jobseeker_profile.hexa_commune.code", allow_null=True)
    codepostalcedex = serializers.CharField(source="jobseeker_profile.hexa_post_code")

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

    def get_adrLibelleVoie(self, obj: User) -> str | None:
        # Remove diacritics and parenthesis from adrLibelleVoie field fixes ASP error 3330
        # (parenthesis are not described as invalid characters in specification document).
        lane = obj.jobseeker_profile.hexa_lane_name
        if lane:
            return unidecode(lane.translate({ord(ch): "" for ch in "()"}))
        return None


class _API_PersonSerializer(serializers.Serializer):
    # Specific field added to the API (not used in ASP transfers)
    NIR = serializers.CharField(source="job_application.job_seeker.jobseeker_profile.nir")

    passIae = serializers.CharField(source="approval_number")
    sufPassIae = NullField()
    idItou = serializers.CharField(source="job_application.job_seeker.jobseeker_profile.asp_uid")

    civilite = serializers.ChoiceField(choices=Title.choices, source="job_application.job_seeker.title")
    nomUsage = serializers.SerializerMethodField()
    nomNaissance = NullField()
    prenom = serializers.SerializerMethodField()
    dateNaissance = serializers.DateField(format="%d/%m/%Y", source="job_application.job_seeker.birthdate")

    codeDpt = serializers.CharField(source="job_application.job_seeker.birth_place.department_code", required=False)
    codeInseePays = serializers.CharField(
        source="job_application.job_seeker.jobseeker_profile.birth_country.code", allow_null=True
    )
    codeGroupePays = serializers.CharField(
        source="job_application.job_seeker.jobseeker_profile.birth_country.group", allow_null=True
    )

    # codeComInsee is only mandatory if birth country is France
    codeComInsee = serializers.SerializerMethodField(required=False)

    passDateDeb = serializers.DateField(format="%d/%m/%Y", source="job_application.approval.start_at")
    passDateFin = serializers.DateField(format="%d/%m/%Y", source="job_application.approval.end_at")

    def get_nomUsage(self, obj: EmployeeRecord) -> str:
        return unidecode(obj.job_application.job_seeker.last_name).upper()

    def get_prenom(self, obj: EmployeeRecord) -> str:
        return unidecode(obj.job_application.job_seeker.first_name).upper()

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


class _API_SituationSerializer(serializers.Serializer):
    niveauFormation = serializers.CharField(source="job_application.job_seeker.jobseeker_profile.education_level")
    salarieEnEmploi = serializers.BooleanField(source="job_application.job_seeker.jobseeker_profile.is_employed")

    salarieSansEmploiDepuis = NullIfEmptyCharField(
        source="job_application.job_seeker.jobseeker_profile.unemployed_since"
    )
    salarieSansRessource = serializers.BooleanField(source="job_application.job_seeker.jobseeker_profile.resourceless")

    inscritPoleEmploi = serializers.BooleanField(source="job_application.job_seeker.jobseeker_profile.pole_emploi_id")
    inscritPoleEmploiDepuis = NullIfEmptyCharField(
        source="job_application.job_seeker.jobseeker_profile.pole_emploi_since"
    )
    numeroIDE = serializers.CharField(source="job_application.job_seeker.jobseeker_profile.pole_emploi_id")

    salarieRQTH = serializers.BooleanField(source="job_application.job_seeker.jobseeker_profile.rqth_employee")
    salarieOETH = serializers.BooleanField(source="job_application.job_seeker.jobseeker_profile.oeth_employee")
    salarieAideSociale = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_social_allowance"
    )

    salarieBenefRSA = serializers.CharField(source="job_application.job_seeker.jobseeker_profile.has_rsa_allocation")
    salarieBenefRSADepuis = NullIfEmptyCharField(
        source="job_application.job_seeker.jobseeker_profile.rsa_allocation_since", allow_blank=True
    )

    salarieBenefASS = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_ass_allocation"
    )
    salarieBenefASSDepuis = NullIfEmptyCharField(
        source="job_application.job_seeker.jobseeker_profile.ass_allocation_since", allow_blank=True
    )

    salarieBenefAAH = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_aah_allocation"
    )
    salarieBenefAAHDepuis = NullIfEmptyCharField(
        source="job_application.job_seeker.jobseeker_profile.aah_allocation_since", allow_blank=True
    )

    salarieBenefATA = serializers.BooleanField(
        source="job_application.job_seeker.jobseeker_profile.has_ata_allocation"
    )
    salarieBenefATADepuis = NullIfEmptyCharField(
        source="job_application.job_seeker.jobseeker_profile.ata_allocation_since", allow_blank=True
    )

    # There is a clear lack of knowledge of ASP business rules on this point.
    # Without any satisfactory answer, it has been decided to obfuscate / mock these fields.
    salarieTypeEmployeur = serializers.CharField(source="asp_employer_type", required=False)
    orienteur = serializers.CharField(source="asp_prescriber_type", required=False)


class EmployeeRecordAPISerializer(serializers.Serializer):
    """
    This serializer is a version with the `numeroAnnexe` field added (financial annex number).

    This field not needed by ASP was simply ignored in earlier versions of the
    main SFTP serializer but was removed for RGPD concerns.
    """

    numLigne = serializers.IntegerField(source="asp_batch_line_number")
    typeMouvement = serializers.CharField(source="ASP_MOVEMENT_TYPE")
    siret = serializers.CharField()
    mesure = serializers.CharField(source="asp_siae_type")

    # See : http://www.tomchristie.com/rest-framework-2-docs/api-guide/fields
    personnePhysique = _API_PersonSerializer(source="*")
    adresse = _API_AddressSerializer(source="job_application.job_seeker")
    situationSalarie = _API_SituationSerializer(source="*")

    # These fields are null at the beginning of the ASP processing
    codeTraitement = serializers.CharField(source="asp_processing_code", allow_blank=True)
    libelleTraitement = serializers.CharField(source="asp_processing_label", allow_blank=True)

    numeroAnnexe = serializers.CharField(source="financial_annex.number", allow_null=True)


class EmployeeRecordUpdateNotificationAPISerializer(serializers.Serializer):
    numLigne = serializers.IntegerField(source="asp_batch_line_number")
    typeMouvement = serializers.CharField(source="ASP_MOVEMENT_TYPE")
    siret = serializers.CharField(source="employee_record.siret")
    mesure = serializers.CharField(source="employee_record.asp_siae_type")

    personnePhysique = _API_PersonSerializer(source="employee_record")
    adresse = _API_AddressSerializer(source="employee_record.job_application.job_seeker")
    situationSalarie = _API_SituationSerializer(source="employee_record")

    # These fields are null at the beginning of the ASP processing
    codeTraitement = serializers.CharField(source="asp_processing_code", allow_blank=True)
    libelleTraitement = serializers.CharField(source="asp_processing_label", allow_blank=True)
