import re

from rest_framework import serializers
from unidecode import unidecode

from itou.employee_record.models import EmployeeRecord
from itou.users.models import User


class _EmployeeSerializer(serializers.ModelSerializer):

    idItou = serializers.CharField(source="jobseeker_hash_id")
    sufPassIae = serializers.CharField(required=False)

    civilite = serializers.ChoiceField(choices=User.Title.choices, source="title")
    nomUsage = serializers.SerializerMethodField()
    prenom = serializers.SerializerMethodField()

    dateNaissance = serializers.DateField(format="%d/%m/%Y", source="birthdate")
    # codeComInsee is only mandatory if birth country is France
    codeComInsee = serializers.CharField(source="birth_place.code", required=False)
    codeDpt = serializers.CharField(source="birth_place.department_code", required=False)
    codeInseePays = serializers.CharField(source="birth_country.code")
    codeGroupePays = serializers.CharField(source="birth_country.group")

    class Meta:
        model = User
        fields = [
            "sufPassIae",
            "idItou",
            "civilite",
            "nomUsage",
            "prenom",
            "dateNaissance",
            "codeComInsee",
            "codeDpt",
            "codeInseePays",
            "codeGroupePays",
        ]

    def get_nomUsage(self, obj):
        return unidecode(obj.last_name).upper()

    def get_prenom(self, obj):
        return unidecode(obj.first_name).upper()

    def to_representation(self, instance):
        result = super().to_representation(instance)

        # Another ASP subtlety, making top-level and children with the same name
        # The commune can be empty if the job seeker is not born in France
        if result.get("codeComInsee"):
            result["codeComInsee"] = {
                "codeComInsee": result.pop("codeComInsee"),
                "codeDpt": result.pop("codeDpt"),
            }
        else:
            # However, if the employee is not born in France
            # the department code must be '099' (error 3411)
            result["codeComInsee"] = {
                "codeComInsee": None,
                "codeDpt": "099",
            }

        # Fields not mapped / ignored
        result["sufPassIae"] = None
        result["nomNaissance"] = None

        return result


class _EmployeeAddressSerializer(serializers.ModelSerializer):

    adrTelephone = serializers.CharField(source="phone", allow_blank=True)
    adrMail = serializers.CharField(source="email", allow_blank=True)

    adrNumeroVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_number")
    codeextensionvoie = serializers.CharField(source="jobseeker_profile.hexa_std_extension", allow_blank=True)
    codetypevoie = serializers.CharField(source="jobseeker_profile.hexa_lane_type")
    adrLibelleVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_name")
    adrCpltDistribution = serializers.CharField(source="jobseeker_profile.hexa_additional_address", allow_blank=True)

    codeinseecom = serializers.CharField(source="jobseeker_profile.hexa_commune.code")
    codepostalcedex = serializers.CharField(source="jobseeker_profile.hexa_post_code")

    class Meta:
        model = User
        # Fields adrMail, adrTelephone
        # are faked out, but kept for conformity with
        # ASP specifications.
        fields = [
            "adrTelephone",
            "adrMail",
            "adrNumeroVoie",
            "codeextensionvoie",
            "codetypevoie",
            "adrLibelleVoie",
            "adrCpltDistribution",
            "codeinseecom",
            "codepostalcedex",
        ]

    def _update_address_and_phone_number(self, result, instance):
        if result.get("adrMail"):
            result["adrMail"] = None

        if result.get("adrTelephone"):
            result["adrTelephone"] = None

        return result

    def to_representation(self, instance):
        result = super().to_representation(instance)

        # Replace these empty strings by JSON null values
        empty_as_null_fields = [
            "codeextensionVoie",
            "adrCpltDistribution",
        ]

        # Don't send extended address if it must be truncated:
        # Do not lower quality of data on itou side
        # Check ASP rule : T030_c026_rg002
        # This rule is badly written, and innacurate (regarding special characters)
        # Follows the acceptable format / RE for this field (now validated by ASP)
        if not re.match("^[a-zA-Z0-9@ ]{,32}$", result.get("adrCpltDistribution")):
            result["adrCpltDistribution"] = None

        # Don't send phone number if not in ASP expected format
        # (we don't want any post-processing or update on this field)
        if result.get("adrTelephone"):
            if not re.match("^\\+?[0-9]{1,16}$", result.get("adrTelephone")):
                result["adrTelephone"] = None

        # By decision, do not display employee e-mail or phone number anymore:
        # ASP has some weird filtering of technically valid email adresses
        # and a phone number format not suitable for most real cases
        # leading to rejection of some employee records
        result = self._update_address_and_phone_number(result, instance)

        # Remove diacritics and parenthesis from adrLibelleVoie field fixes ASP error 3330
        # (parenthesis are not described as invalid characters in specification document)
        if lane := result.get("adrLibelleVoie"):
            result["adrLibelleVoie"] = unidecode(lane.translate({ord(ch): "" for ch in "()"}))

        for field in empty_as_null_fields:
            if result.get(field) == "":
                result[field] = None

        return result


class _EmployeeSituationSerializer(serializers.ModelSerializer):

    # Placeholder: updated at top-level serialization
    orienteur = serializers.CharField(required=False)

    niveauFormation = serializers.CharField(source="jobseeker_profile.education_level")
    salarieEnEmploi = serializers.BooleanField(source="jobseeker_profile.is_employed")

    # Placeholder: updated at top-level serialization
    salarieTypeEmployeur = serializers.CharField(required=False)

    salarieSansEmploiDepuis = serializers.CharField(source="jobseeker_profile.unemployed_since")
    salarieSansRessource = serializers.BooleanField(source="jobseeker_profile.resourceless")

    inscritPoleEmploi = serializers.BooleanField(source="pole_emploi_id")
    inscritPoleEmploiDepuis = serializers.CharField(source="jobseeker_profile.pole_emploi_since")
    numeroIDE = serializers.CharField(source="pole_emploi_id")

    salarieRQTH = serializers.BooleanField(source="jobseeker_profile.rqth_employee")
    salarieOETH = serializers.BooleanField(source="jobseeker_profile.oeth_employee")
    salarieAideSociale = serializers.BooleanField(source="jobseeker_profile.has_social_allowance")

    salarieBenefRSA = serializers.CharField(source="jobseeker_profile.has_rsa_allocation")
    salarieBenefRSADepuis = serializers.CharField(source="jobseeker_profile.rsa_allocation_since", allow_blank=True)

    salarieBenefASS = serializers.BooleanField(source="jobseeker_profile.has_ass_allocation")
    salarieBenefASSDepuis = serializers.CharField(source="jobseeker_profile.ass_allocation_since", allow_blank=True)

    salarieBenefAAH = serializers.BooleanField(source="jobseeker_profile.has_aah_allocation")
    salarieBenefAAHDepuis = serializers.CharField(source="jobseeker_profile.aah_allocation_since", allow_blank=True)

    salarieBenefATA = serializers.BooleanField(source="jobseeker_profile.has_ata_allocation")
    salarieBenefATADepuis = serializers.CharField(source="jobseeker_profile.ata_allocation_since", allow_blank=True)

    class Meta:
        model = User
        fields = [
            "orienteur",
            "niveauFormation",
            "salarieEnEmploi",
            "salarieTypeEmployeur",
            "salarieSansEmploiDepuis",
            "salarieSansRessource",
            "inscritPoleEmploi",
            "inscritPoleEmploiDepuis",
            "numeroIDE",
            "salarieRQTH",
            "salarieOETH",
            "salarieAideSociale",
            "salarieBenefRSA",
            "salarieBenefRSADepuis",
            "salarieBenefASS",
            "salarieBenefASSDepuis",
            "salarieBenefAAH",
            "salarieBenefAAHDepuis",
            "salarieBenefATA",
            "salarieBenefATADepuis",
        ]

    def to_representation(self, instance):
        result = super().to_representation(instance)

        # Replace these empty strings by JSON null values
        empty_as_null_fields = [
            "inscritPoleEmploi",
            "inscritPoleEmploiDepuis",
            "salarieSansEmploiDepuis",
            "salarieBenefRSADepuis",
            "salarieBenefASSDepuis",
            "salarieBenefAAHDepuis",
            "salarieBenefATADepuis",
        ]

        for field in empty_as_null_fields:
            if result.get(field) == "":
                result[field] = None

        return result


class EmployeeRecordSerializer(serializers.ModelSerializer):

    # Placeholder: not the final position in the JSON result
    passIae = serializers.CharField(source="approval_number")
    passDateDeb = serializers.DateField(format="%d/%m/%Y", source="approval.start_at")
    passDateFin = serializers.DateField(format="%d/%m/%Y", source="approval.end_at")

    numLigne = serializers.IntegerField(source="asp_batch_line_number")
    typeMouvement = serializers.CharField(source="ASP_MOVEMENT_TYPE")

    mesure = serializers.CharField(source="asp_siae_type")
    # Note that this is the "parent" SIRET (for antennas)
    siret = serializers.CharField()

    personnePhysique = _EmployeeSerializer(source="job_application.job_seeker")
    adresse = _EmployeeAddressSerializer(source="job_application.job_seeker")
    situationSalarie = _EmployeeSituationSerializer(source="job_application.job_seeker")

    # These fields are null at the beginning of the ASP processing
    codeTraitement = serializers.CharField(source="asp_processing_code", allow_blank=True)
    libelleTraitement = serializers.CharField(source="asp_processing_label", allow_blank=True)

    class Meta:
        model = EmployeeRecord
        fields = [
            "passIae",
            "passDateDeb",
            "passDateFin",
            "numLigne",
            "typeMouvement",
            "mesure",
            "siret",
            "personnePhysique",
            "adresse",
            "situationSalarie",
            "codeTraitement",
            "libelleTraitement",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        """
        Overriding this method allows fine-tuning final JSON rendering

        For EmployeeRecord objects, we just want to push-down
        some top-level fields into the JSON objects hierarchy.
        """

        result = super().to_representation(instance)

        # Get 'passIae' field out of root level
        # and stick it into the personnePhysique JSON object
        person = result["personnePhysique"]
        person["passIae"] = result.pop("passIae")

        # Update from ASP : v1.0.2
        # Adding start and end date of approval in the "Person" section
        person["passDateDeb"] = result.pop("passDateDeb")
        person["passDateFin"] = result.pop("passDateFin")

        # At first position (this is an OrderedDict)
        person.move_to_end("passIae", last=False)

        # 'employerType' is top-level but must be inserted in 'situationSalarie'
        employee_situation = result["situationSalarie"]
        employee_situation["salarieTypeEmployeur"] = instance.asp_employer_type

        # same workaround for prescriber type (orienteur)
        employee_situation["orienteur"] = instance.tmp_asp_prescriber_type

        return result


class EmployeeRecordBatchSerializer(serializers.Serializer):
    """
    This serializer is a wrapper for a list of employee records
    """

    msgInformatif = serializers.CharField(source="message")
    telId = serializers.CharField(source="id", allow_blank=True)
    lignesTelechargement = EmployeeRecordSerializer(many=True, source="employee_records")
