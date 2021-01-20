from django.db import models
from django.forms import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.approvals.models import Approval
from itou.asp.models import Commune, Country, Department, EducationLevel
from itou.eligibility.models import EligibilityDiagnosis
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae, SiaeFinancialAnnex
from itou.users.models import User
from itou.utils.apis.geocoding import detailed_geocoding_data, get_geocoding_data
from itou.utils.validators import validate_siret


# INSEE codes
# Are needed for:
# - the current living address of the employee
# - the birth place of the employee


class EmployeeRecordQuerySet(models.QuerySet):
    pass


class EmployeeRecord(models.Model):
    """
    EmployeeRecord - Fiche salarié

    Holds information needed for JSON exports of "fiches salariés" to ASP

    Relies heavily on 'asp' Django app.
    """

    # EmployeeRecord is only relevant for these kind of SIAE
    class Kind(models.TextChoices):
        EI = "EI", _("Entreprise d'insertion")
        ACI = "ACI", _("Atelier chantier d'insertion")
        ETTI = "ETTI", _("Entreprise de travail temporaire d'insertion")

    # Current possible statuses for an EmployeeRecord (WIP?)
    class Status(models.TextChoices):
        NEW = "NEW", _("Nouvelle fiche salarié")
        COMPLETE = "COMPLETE", _("Données complètes")
        SENT = "SENT", _("Envoyée ASP")
        REFUSED = "REFUSED", _("Rejet ASP")
        PROCESSED = "PROCESSED", _("Traitée ASP")

    # TODO Maybe too specifiic, move to ASP ?
    # ..

    siret = models.CharField(verbose_name=_("Siret"), max_length=14, validators=[validate_siret])

    # kind:
    # kept the same name as in SIAE and prescriber models.
    # The kind of a structure is refered as "mesure" for ASP
    kind = models.CharField(verbose_name=_("Type"), max_length=4, choices=Kind.choices)

    # status:
    # Employee record cycle of life:
    # - New: newly created
    # - Complete: all required fields are present to generate a JSON output
    # - Sent: When complete, JSON export can be sent to ASP
    # - Refused: For any reason reject by ASP, can be updated and submited again
    # - Processed: Sent to ASP and got positive feedback of processing by ASP. Can not be changed anymore
    status = models.CharField(verbose_name=_("Etat"), max_length=10, choices=Status.choices, default=Status.NEW)

    # Once sent to ASP, we expect asynchronous feedback
    # This code is filled once ASP has provided feddback on the transmission
    # of a list of employee records
    # For details on ref codes refer to theoriginal ASP project requirements document
    asp_process_code = models.CharField(verbose_name=_("Code de traitement ASP"), max_length=4, null=True)

    # TODO Store refusal reason from ASP ?

    # json:
    # Once the employee record has reached its final state (TBD), it can't be updated.
    # However related / linked objects live their lives and are subject to changes.
    # The json field is an immutable representation of the employee record actually
    # sent to ASP and act as proof.
    json = models.JSONField(verbose_name=_("Fiche salarié (JSON)"), null=True)
    process_response = models.JSONField(verbose_name=_("Réponse traitement ASP"))

    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), null=True)

    # Link to financial annex, mainlu for its number
    financial_annex = models.ForeignKey(SiaeFinancialAnnex, on_delete=models.CASCADE)

    # Some information in the eligibility diagnosis can be used in the ER
    eligibility_diagnosis = models.ForeignKey(EligibilityDiagnosis, on_delete=models.CASCADE)

    # Link the approval, mainly for its number
    approval = models.ForeignKey(Approval, on_delete=models.CASCADE)

    # Employee
    # ---
    # An employee / User currently have the following needed information:
    # -
    # - personnePhysique.passIae: if user has a valid PASS IAE
    # - personnePhysique.dateNaissance
    # - personnePhysique.idItou: will be generated
    # - personnePhysique.prenom
    # - personnePhysique.prenom
    # Most information of the "adresse" part of the JSON ER can also befound in User model:
    # - adresse.adrTelephone: user.
    # - adresse.adrMail
    # - adresse.codepostalcedex
    # Not captured yet:
    # - personnePhysique.civilite
    # - personnePhysique.nomNaissance
    # - personnePhysique.codeComInsee.codeComInsee
    # - personnePhysique.codeComInsee.codeDpt
    employee = models.ForeignKey(User, verbose_name=_("Employé"), on_delete=models.CASCADE)
    educational_leval = models.ForeignKey(
        EducationLevel,
        verbose_name=("Niveau de formation"),
        on_delete=models.SET_NULL,
        null=True,
    )
    birth_place = models.ForeignKey(
        Commune,
        verbose_name=_("Commune de naissance"),
        on_delete=models.SET_NULL,
        null=True,
    )
    birth_country = models.ForeignKey(
        Country,
        verbose_name=_("Pays de naissance"),
        on_delete=models.SET_NULL,
        null=True,
    )

    # birth_place = models.ForeignKey(INSEECode, verbose_name=_("Lieu de naissance"))

    class Meta:
        verbose_name = _("Fiche salarié")
        # An Employee record is unique for a given SIRET and Approval (number)
        unique_together = ("siret", "approval")

    def __str__(self):
        return f"EmployeeRecord:SIRET={self.siret},PASS-IAE={self.approval.number}"

    def clean(self):
        # Employee record can't be updated anymore if in "final" status
        if not self.is_updatable:
            raise ValidationError(_("Cette fiche salarié est historisée et non-modifiable"))
        return super.clean()

    def save(self, *args, **kwargs):
        # When not using a form for updating / creating EmployeeRecord objects
        # performing a clean on the model will ensure some constraints are checked
        self.clean()
        if self.pk:
            self.updated_at = timezone.now()
        return super.save(*args, **kwargs)

    @property
    def is_updatable(self):
        """
        Once in final state (PROCESSED), an EmployeeRecord is not updatable anymore.
        See model save() and clean() method.
        """
        return not (self.status == self.kind.STATUS_PROCESSED and self.json is not None)

    @property
    def set_complete(self):
        pass

    @staticmethod
    def convert_kind_to_asp_id(kind):
        """
        Conversion of Siae.kind field value to ASP employer type
        i.e. field `rte_code_type_employeur` of ASP reference file: ref_type_employeur_v3.csv

        Employer code is coded in one char.

        ASP has a code 5 for ESAT (not used)
        """
        if kind == Siae.KIND_EI:
            return "1"
        elif kind == Siae.KIND_ETTI:
            return "2"
        elif kind == Siae.KIND_AI:
            return "3"
        elif kind == Siae.KIND_ACI:
            return "4"
        elif kind == Siae.KIND_EA:
            return "6"
        else:
            return "7"  # Other / "Autres"
