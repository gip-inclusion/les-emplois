from django.db import models


class PEApiEndpoint(models.TextChoices):
    RECHERCHE_INDIVIDU = "rech_individu"
    MISE_A_JOUR_PASS_IAE = "maj_pass"


class PEApiPreliminaryCheckFailureReason(models.TextChoices):
    MISSING_USER_DATA = "MISSING_USER_DATA", "Utilisateur manquant de données, non essayé."
    NO_JOB_APPLICATION = "NO_JOB_APPLICATION", "L'agrément n'est lié à aucune candidature acceptée"
    STARTS_IN_FUTURE = "STARTS_IN_FUTURE", "L'agrément démarre dans le futur"
    INVALID_SIAE_KIND = "INVALID_SIAE_KIND", "Code structure invalide"


class PEApiRechercheIndividuExitCode(models.TextChoices):
    S000 = "S000", "Aucun individu trouvé"
    S001 = "S001", "Individu trouvé"
    S002 = "S002", "Plusieurs individu trouvés"
    R010 = "R010", "NIR Certifié absent"
    R011 = "R011", "NIR Certifié incorrect"
    R020 = "R020", "Nom de naissance absente"
    R021 = "R021", "Nom de naissance incorrect"
    R030 = "R030", "Prénom absent"
    R031 = "R031", "Prénom incorrect"
    R040 = "R040", "Date de naissance absente"
    R041 = "R041", "Date de naissance incorrecte"
    R042 = "R042", "Date de naissance invalide"


class PEApiMiseAJourPassExitCode(models.TextChoices):
    S000 = "S000", "Suivi délégué installé"
    S001 = "S001", "SD non installé : Identifiant national individu obligatoire"
    S002 = "S002", "SD non installé : Code traitement obligatoire"
    S003 = "S003", "SD non installé : Code traitement erroné"
    S004 = "S004", "SD non installé : Erreur lors de la recherche de la TDV référente"
    S005 = "S005", "SD non installé : Identifiant régional de l’individu obligatoire"
    S006 = "S006", "SD non installé : Code Pôle Emploi de l’individu obligatoire"
    S007 = "S007", "SD non installé : Individu inexistant en base"
    S008 = "S008", "SD non installé : Individu radié"
    S009 = "S009", "SD non installé : Inscription incomplète de l’individu "
    S010 = "S010", "SD non installé : PEC de l’individu inexistante en base"
    S011 = "S011", "SD non installé : Demande d’emploi de l’individu inexistante en base"
    S012 = "S012", "SD non installé : Suivi principal de l’individu inexistant en base"
    S013 = "S013", "SD non installé : Référent suivi principal non renseigné en base"
    S014 = "S014", "SD non installé : Structure suivi principal non renseignée en base"
    S015 = "S015", "SD non installé : Suivi délégué déjà en cours"
    S016 = "S016", "SD non installé : Problème lors de la recherche du dernier suivi délégué"
    S017 = "S017", "SD non installé : Type de suivi de l’individu non EDS»"
    S018 = "S018", "SD non installé : Type de SIAE obligatoire"
    S019 = "S019", "SD non installé : Type de SIAE erroné"
    S020 = "S020", "SD non installé : Statut de la réponse obligatoire"
    S021 = "S021", "SD non installé : Statut de la réponse erroné"
    S022 = "S022", "SD non installé : Refus du PASS IAE"
    S023 = "S023", "SD non installé : Date de début du PASS IAE obligatoire"
    S024 = "S024", "SD non installé : Date de début du PASS IAE dans le futur"
    S025 = "S025", "SD non installé : Date de fin du PASS IAE obligatoire"
    S026 = "S026", "SD non installé : Date fin PASS IAE non strictement sup à date début"
    S027 = "S027", "SD non installé : Numéro du PASS IAE obligatoire"
    S028 = "S028", "SD non installé : Origine de la candidature obligatoire"
    S029 = "S029", "SD non installé : Origine de la candidature erronée"
    S031 = "S031", "SD non installé : Numéro SIRET SIAE obligatoire"
    S032 = "S032", "SD non installé : Organisme générique inexistant dans réf partenaire"
    S033 = "S033", "SD non installé : Conseiller prescripteur inexistant en base"
    S034 = "S034", "SD non installé : Structure prescripteur inexistante en base"
    S035 = "S035", "SD non installé : Type de structure du prescripteur erroné"
    S036 = "S036", "SD non installé : Pas de lien entre structure prescripteur et partenaire"
    S037 = "S037", "SD non installé : Organisme générique inexistant en base"
    S038 = "S038", "SD non installé : Correspondant du partenaire inexistant en base"
    S039 = "S039", "SD non installé : Structure correspondant inexistante en base"
    S040 = "S040", "SD non installé : Structure correspondant inexistante dans réf des struct"
    S041 = "S041", "SD non installé : Structure de suivi non autorisée"
    S042 = "S042", "SD non installé : Adresse du correspondant inexistante en base"
    S043 = "S043", "SD non installé : Commune du correspondant inexistante en base"
    E_ERR_D98_D_PR_PROBLEME_TECHNIQUE = "E_ERR_D98_D_PR_PROBLEME_TECHNIQUE", "Problème technique inconnu"
    E_ERR_EX042_PROBLEME_DECHIFFREMEMENT = (
        "E_ERR_EX042_PROBLEME_DECHIFFREMEMENT",
        "Erreur lors du déchiffrement du NIR chiffré",
    )


class PEApiNotificationStatus(models.TextChoices):
    """Handles possible values for the 'pe_notification_status' field.

    The default value is PENDING, meaning we never tried to notify PE yet.

    Then it could be:
    - READY if the approval can be sent (all the required fields are present and the approval has already started)
    - SUCCESS if the whole notification was indeed an acknowledged success
    - SHOULD_RETRY if we encountered recoverable errors along the way
    - ERROR in the case of unrecoverable errors, in which case:
      * the concerned API would be stored in the pe_notification_endpoint field
      * the error code would be stored in the pe_notification_exit_code field

    [DISCARDED OTHER POSSIBILITY BELOW]
    Another way of doing it would be to create a grammar on the pe_notification_status
    field, think: allowing values in the form ERROR.[RECH|MAJ].<ERROR_CODE>. Examples:

        ERROR.RECH.S000 = no individual found for this NIR on PE side
        ERROR.MAJ.S008 = individual was banned

    This allows for 2 less fields, but I find it a little hackier for no extremely good reason.
    Let's have specialized fields instead of designing something that will force us to
    use search wildcards on a poor column of a huge table.
    """

    PENDING = "notification_pending"
    READY = "notification_ready"
    SUCCESS = "notification_success"
    ERROR = "notification_error"
    # HTTP errors: timeouts, DNS issues, bad auth, too many requests.
    SHOULD_RETRY = "notification_should_retry"
