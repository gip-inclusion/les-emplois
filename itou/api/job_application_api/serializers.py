from rest_framework import serializers

from itou.approvals.enums import ApprovalStatus
from itou.companies.enums import CompanyKind
from itou.companies.models import JobDescription
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplication
from itou.prescribers.enums import PrescriberOrganizationKind


def _get_job_description_city(job_description):
    if job_description:
        if job_description.location:
            return job_description.location.name
        return job_description.company.city


class JobDescriptionSerializer(serializers.ModelSerializer):
    rome = serializers.CharField(source="appellation.rome.code", allow_null=True, label="Code ROME")
    titre = serializers.CharField(source="appellation.rome.name", allow_null=True, label="Intitulé du poste")
    ville = serializers.SerializerMethodField(label="Ville du poste")

    class Meta:
        model = JobDescription
        fields = ("rome", "titre", "ville")
        read_only_fields = fields

    def get_ville(self, obj) -> str | None:
        return _get_job_description_city(obj)


class JobApplicationSearchResponseSerializer(serializers.ModelSerializer):
    identifiant_unique = serializers.UUIDField(
        source="pk",
        label="Identifiant unique de la candidature",
    )
    cree_le = serializers.DateTimeField(
        source="created_at",
        label="Horodatage de création de la candidature (ISO 8601)",
    )
    mis_a_jour_le = serializers.DateTimeField(
        source="updated_at",
        label="Horodatage de dernière mise à jour de la candidature (ISO 8601)",
        help_text=(
            "**Non destiné à l’affichage.**\n\n"
            "Correspond à l’horodatage le plus récent lors duquel la candidature a été modifiée.\n\n"
            "Ces modifications peuvent être des traitements automatisés.\n\n"
            "Idéal pour déterminer si une entrée doit être mise à jour sur une base externe."
        ),
    )
    dernier_changement_le = serializers.DateTimeField(
        source="last_modification_at",
        label="Horodatage du dernier changement de la candidature (ISO 8601)",
        help_text="Correspond à l’horodatage le plus récent lors duquel la candidature a changé d’état.",
    )
    statut = serializers.ChoiceField(
        source="state",
        choices=JobApplicationState.choices,
        label="État de la candidature",
    )
    candidat_nir = serializers.CharField(
        source="job_seeker.jobseeker_profile.nir",
        label="Numéro de sécurité sociale du candidat",
    )
    candidat_nom = serializers.CharField(
        source="job_seeker.last_name",
        label="Nom de famille du candidat",
    )
    candidat_prenom = serializers.CharField(
        source="job_seeker.first_name",
        label="Prénom du candidat",
    )
    candidat_date_naissance = serializers.DateField(
        source="job_seeker.jobseeker_profile.birthdate",
        label="Date de naissance du candidat (ISO 8601)",
    )
    candidat_email = serializers.CharField(
        source="job_seeker.email",
        label="Adresse e-mail du candidat",
    )
    candidat_telephone = serializers.CharField(
        source="job_seeker.phone",
        label="Téléphone du candidat",
    )
    candidat_pass_iae_statut = serializers.ChoiceField(
        source="job_seeker.latest_approval.state",
        choices=ApprovalStatus.choices,
        allow_null=True,
        label="Statut du PASS IAE",
    )
    candidat_pass_iae_numero = serializers.CharField(
        source="job_seeker.latest_approval.number",
        allow_null=True,
        label="Numéro de PASS IAE",
    )
    candidat_pass_iae_date_debut = serializers.DateField(
        source="job_seeker.latest_approval.start_at",
        allow_null=True,
        label="Date de début du PASS IAE (ISO 8601)",
    )
    candidat_pass_iae_date_fin = serializers.DateField(
        source="job_seeker.latest_approval.end_at",
        allow_null=True,
        label="Date de fin du PASS IAE (ISO 8601)",
    )
    entreprise_type = serializers.ChoiceField(
        source="to_company.kind",
        choices=CompanyKind.choices,
        label="Type d’entreprise",
    )
    entreprise_nom = serializers.CharField(
        source="to_company.display_name",
        label="Nom de l’entreprise",
    )
    entreprise_siret = serializers.SerializerMethodField(
        label="SIRET de l’entreprise",
        help_text=(
            "Le SIREN de l’organisation mère est susceptible d’être retourné pour des structures "
            "dont le SIRET est inconnu."
        ),
    )
    entreprise_adresse = serializers.CharField(
        source="to_company.address_on_one_line",
        label="Adresse postale de l’entreprise",
    )
    entreprise_employeur_email = serializers.CharField(
        source="employer_email",
        label="Adresse e-mail de l’employeur",
    )
    orientation_emetteur_type = serializers.ChoiceField(
        source="sender_kind",
        choices=SenderKind.choices,
        label="Type d’émetteur",
    )
    orientation_emetteur_sous_type = serializers.SerializerMethodField(
        allow_null=True,
        label="Sous-type d’émetteur",
        help_text=(
            "\n**Selon le type, les sous-types suivants sont applicables:**\n"
            "\n- **_Employeur :_** \n"
            f"""{"\n".join([f"    - `{value}` : {label}" for value, label in CompanyKind.choices])}"""
            "\n- **_Prescripteur :_** \n"
            f"""{"\n".join([f"    - `{value}` : {label}" for value, label in PrescriberOrganizationKind.choices])}"""
        ),
    )
    orientation_emetteur_nom = serializers.CharField(
        source="sender.last_name",
        allow_null=True,
        label="Nom de famille de l’émetteur",
    )
    orientation_emetteur_prenom = serializers.CharField(
        source="sender.first_name",
        allow_null=True,
        label="Prénom de l’émetteur",
    )
    orientation_emetteur_email = serializers.CharField(
        source="sender.email",
        allow_null=True,
        label="Adresse e-mail de l’émetteur",
    )
    orientation_emetteur_organisme = serializers.SerializerMethodField(
        allow_null=True,
        label="Nom de la structure de l’émetteur",
    )
    orientation_emetteur_organisme_telephone = serializers.SerializerMethodField(
        allow_null=True,
        label="Téléphone de la structure de l’émetteur",
    )
    orientation_postes_recherches = JobDescriptionSerializer(
        source="selected_jobs",
        many=True,
        label="Postes recherchés par le candidat",
    )
    orientation_candidat_message = serializers.CharField(
        source="message",
        label="Message de candidature",
        help_text=(
            "Le message est potentiellement rédigé sur plusieurs lignes.\n\n"
            "Des marqueurs de sauts de ligne tels que `\\n` ou `\\r\\n` peuvent être inclus dans le message.\n\n"
            "**Il conviendra de les échapper ou de les convertir au besoin.**"
        ),
    )
    orientation_candidat_cv = serializers.CharField(
        source="resume_link",
        label="Lien vers le CV du candidat",
    )
    contrat_date_debut = serializers.DateField(
        source="hiring_start_at",
        label="Date de début du contrat (ISO 8601)",
    )
    contrat_date_fin = serializers.DateField(
        source="hiring_end_at",
        label="Date de fin du contrat (ISO 8601)",
    )
    contrat_poste_retenu = JobDescriptionSerializer(
        source="hired_job",
        allow_null=True,
        label="Poste retenu",
    )

    class Meta:
        model = JobApplication
        fields = (
            "identifiant_unique",
            "cree_le",
            "mis_a_jour_le",
            "dernier_changement_le",
            "statut",
            "candidat_nir",
            "candidat_nom",
            "candidat_prenom",
            "candidat_date_naissance",
            "candidat_email",
            "candidat_telephone",
            "candidat_pass_iae_statut",
            "candidat_pass_iae_numero",
            "candidat_pass_iae_date_debut",
            "candidat_pass_iae_date_fin",
            "entreprise_type",
            "entreprise_nom",
            "entreprise_siret",
            "entreprise_adresse",
            "entreprise_employeur_email",
            "orientation_emetteur_type",
            "orientation_emetteur_sous_type",
            "orientation_emetteur_nom",
            "orientation_emetteur_prenom",
            "orientation_emetteur_email",
            "orientation_emetteur_organisme",
            "orientation_emetteur_organisme_telephone",
            "orientation_postes_recherches",
            "orientation_candidat_message",
            "orientation_candidat_cv",
            "contrat_date_debut",
            "contrat_date_fin",
            "contrat_poste_retenu",
        )
        read_only_fields = fields

    def get_entreprise_siret(self, obj) -> str:
        if obj.to_company.source == obj.to_company.SOURCE_USER_CREATED:
            return obj.to_company.siret[:9]
        return obj.to_company.siret

    def _get_sender_org(self, obj):
        if obj.sender_kind == SenderKind.PRESCRIBER and obj.sender_prescriber_organization:
            return obj.sender_prescriber_organization
        elif obj.sender_kind == SenderKind.EMPLOYER and obj.sender_company:
            return obj.sender_company

    def get_orientation_emetteur_sous_type(self, obj) -> CompanyKind | PrescriberOrganizationKind | None:
        if sender_org := self._get_sender_org(obj):
            return sender_org.kind

    def get_orientation_emetteur_organisme(self, obj) -> str | None:
        if sender_org := self._get_sender_org(obj):
            return sender_org.name

    def get_orientation_emetteur_organisme_telephone(self, obj) -> str | None:
        if sender_org := self._get_sender_org(obj):
            return sender_org.phone


class JobApplicationSearchRequestSerializer(serializers.Serializer):
    nir = serializers.CharField(write_only=True, label="Numéro de sécurité sociale du candidat")
    nom = serializers.CharField(write_only=True, label="Nom de famille du candidat")
    prenom = serializers.CharField(write_only=True, label="Prénom du candidat")
    date_naissance = serializers.DateField(write_only=True, label="Date de naissance du candidat (ISO 8601)")
