from rest_framework import serializers

from itou.employee_record.models import EmployeeRecord
from itou.users.models import User


class _EmployeeSerializer(serializers.ModelSerializer):

    idItou = serializers.CharField(source="jobseeker_hash_id")

    civilite = serializers.ChoiceField(choices=User.Title.choices, source="title")
    nomUsage = serializers.CharField(source="last_name")
    prenom = serializers.CharField(source="first_name")

    dateNaissance = serializers.DateField(format="%d/%m/%Y", source="birthdate")
    codeComInsee = serializers.IntegerField(source="birth_place.code")
    codeDpt = serializers.CharField(source="birth_place.department_code")
    codeInseePays = serializers.IntegerField(source="birth_country.code")
    codeGroupePays = serializers.IntegerField(source="birth_country.group")

    class Meta:
        model = User
        fields = [
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

    def to_representation(self, instance):
        result = super().to_representation(instance)

        # Another ASP subtlety, making top-level and children with the same name
        result["codeComInsee"] = {
            "codeComInsee": result.pop("codeComInsee"),
            "codeDpt": result.pop("codeDpt"),
        }

        return result


class _EmployeeAddress(serializers.ModelSerializer):

    adrTelephone = serializers.CharField(source="phone")
    adrEmail = serializers.CharField(source="email")

    adrNumeroVoie = serializers.IntegerField(source="jobseeker_profile.hexa_lane_number")
    codeextensionVoie = serializers.CharField(source="jobseeker_profile.hexa_std_extension")
    codetypeVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_type")
    adrLibelleVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_name")

    codeinseecom = serializers.IntegerField(source="jobseeker_profile.hexa_commune.code")
    codepostalcedex = serializers.CharField(source="jobseeker_profile.hexa_post_code")

    class Meta:
        model = User
        fields = [
            "adrTelephone",
            "adrEmail",
            "adrNumeroVoie",
            "codeextensionVoie",
            "codetypeVoie",
            "adrLibelleVoie",
            "codeinseecom",
            "codepostalcedex",
        ]


class _EmployeeSituation(serializers.ModelSerializer):

    # Placeholder: updated at top-level serialization
    orienteur = serializers.CharField(required=False)

    niveauFormation = serializers.IntegerField(source="jobseeker_profile.education_level")
    salarieEnEmploi = serializers.BooleanField(source="jobseeker_profile.is_employed")

    # Placeholder: updated at top-level serialization
    salarieTypeEmployeur = serializers.CharField(required=False)

    salarieSansEmploiDepuis = serializers.CharField(source="jobseeker_profile.unemployed_since")
    salarieSansRessource = serializers.CharField(source="jobseeker_profile.resourceless")

    inscritPoleEmploi = serializers.BooleanField(source="pole_emploi_id")
    inscritPoleEmploiDepuis = serializers.CharField(source="jobseeker_profile.pole_emploi_since")
    numeroIDE = serializers.CharField(source="pole_emploi_id")

    salarieRQTH = serializers.BooleanField(source="jobseeker_profile.rqth_employee")
    salarieOETH = serializers.BooleanField(source="jobseeker_profile.oeth_employee")
    salarieAideSociale = serializers.BooleanField(source="jobseeker_profile.has_social_allowance")

    salarieBenefRSA = serializers.BooleanField(source="jobseeker_profile.has_rsa_allocation")
    salarieBenefRSADepuis = serializers.CharField(source="jobseeker_profile.rsa_allocation_since")

    salarieBenefASS = serializers.BooleanField(source="jobseeker_profile.has_ass_allocation")
    salarieBenefASSDepuis = serializers.CharField(source="jobseeker_profile.ass_allocation_since")

    salarieBenefAAH = serializers.BooleanField(source="jobseeker_profile.has_aah_allocation")
    salarieBenefAAHDepuis = serializers.CharField(source="jobseeker_profile.aah_allocation_since")

    salarieBenefATA = serializers.BooleanField(source="jobseeker_profile.has_ata_allocation")
    salarieBenefATADepuis = serializers.CharField(source="jobseeker_profile.ata_allocation_since")

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


class EmployeeRecordSerializer(serializers.ModelSerializer):

    # Placeholder: not the final position in the JSON result
    passIae = serializers.CharField(source="approval_number")

    numLigne = serializers.IntegerField(source="batch_line_number")
    typeMouvement = serializers.CharField(source="movement_type")
    mesure = serializers.CharField(source="asp_siae_type")
    siret = serializers.CharField(source="job_application.to_siae.siret")

    personnePhysique = _EmployeeSerializer(source="job_application.job_seeker")
    adresse = _EmployeeAddress(source="job_application.job_seeker")
    situationSalarie = _EmployeeSituation(source="job_application.job_seeker")

    # These fields are null at the beginning of the ASP processing
    codeTraitement = serializers.CharField(source="asp_processing_code")
    libelleTraitement = serializers.CharField(source="asp_processing_label")

    class Meta:
        model = EmployeeRecord
        fields = [
            "passIae",
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

        # At first position (this is an OrderedDict)
        person.move_to_end("passIae", last=False)

        # 'employerType' is top-level but must be inserted in 'situationSalarie'
        employee_situation = result["situationSalarie"]
        employee_situation["salarieTypeEmployeur"] = instance.asp_employer_type

        # same workaroud for prescriber type (orienteur)
        employee_situation["orienteur"] = instance.asp_prescriber_type

        return result
