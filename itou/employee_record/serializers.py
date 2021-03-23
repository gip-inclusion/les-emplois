from rest_framework import serializers

from itou.employee_record.models import EmployeeRecord
from itou.users.models import User


class RemoveEmptyStringSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):

        print(self.data)
        print(self.__dict__)

        return super().to_representation(instance)


class _EmployeeSerializer(serializers.ModelSerializer):

    idItou = serializers.IntegerField(source="id")

    civilite = serializers.ChoiceField(choices=User.Title.choices, source="title")
    nomUsage = serializers.CharField(source="last_name")
    prenom = serializers.CharField(source="first_name")

    dateNaissance = serializers.DateField(format="%d/%m/%Y", source="birthdate")
    codeComInsee = serializers.IntegerField(source="birth_place.code")
    # TBD birth dpt
    codeInseePays = serializers.IntegerField(source="birth_country.code")
    # Nationalité TBD
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
            "codeInseePays",
            "codeGroupePays",
        ]


class _EmployeeAddress(serializers.ModelSerializer):

    adrTelephone = serializers.CharField(source="phone")
    adrEmail = serializers.CharField(source="email")

    adrNumeroVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_number")
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

    niveauFormation = serializers.CharField(source="jobseeker_profile.education_level")
    salarieEnEmploi = serializers.BooleanField(source="jobseeker_profile.is_employed")

    # TBD: employer type and orienter

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
            "niveauFormation",
            "salarieEnEmploi",
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

    passIae = serializers.CharField(max_length=12, source="approval_number")
    personnePhysique = _EmployeeSerializer(source="job_application.job_seeker")
    adresse = _EmployeeAddress(source="job_application.job_seeker")
    situationSalarie = _EmployeeSituation(source="job_application.job_seeker")

    class Meta:
        model = EmployeeRecord
        fields = [
            "passIae",
            "personnePhysique",
            "adresse",
            "situationSalarie",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        result = super().to_representation(instance)

        print(result)

        # Get passIae field out of root level
        # and stick it into the personnePhysique JSON object
        person = result["personnePhysique"]
        person["passIae"] = result.pop("passIae")
        # At first position (this is an OrderedDict)
        person.move_to_end("passIae", last=False)

        return result
