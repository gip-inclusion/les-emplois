from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis
from itou.siae.models import FinancialAnnex
from itou.users.models import User
from itou.utils.validators import validate_siret


class EmployeeRecord(models.Model):
    """
    EmployeeRecord - Fiche salarié

    Holds information needed for JSON exports of "fiches salariés" to ASP
    """

    # ER are only possible for these kind of SIAE
    KIND_EI = "EI"
    KIND_ACI = "ACI"
    KIND_ETTI = "ETTI"

    KIND_CHOICES = (
        (KIND_EI, _("Entreprise d'insertion")),
        (KIND_ACI, _("Atelier chantier d'insertion")),
        (KIND_ETTI, _("Entreprise de travail temporaire d'insertion")),
    )

    # Current possible statuses for an EmployeeRecord
    STATUS_NEW = "NEW"
    STATUS_COMPLETE = "COMPLETE"
    STATUS_SENT = "SENT"
    STATUS_REFUSED = "REFUSED"
    STATUS_PROCESSED = "PROCESSED"

    STATUS_CHOICES = (
        (STATUS_NEW, _("Nouvelle fiche salarié")),
        (STATUS_COMPLETE, _("Données complètes")),
        (STATUS_SENT, _("Envoyée ASP")),
        (STATUS_REFUSED, _("Rejet ASP")),
        (STATUS_PROCESSED, _("Traitée ASP")),
    )
    # ..

    siret = models.CharField(verbose_name=_("Siret"), max_length=14, validators=[validate_siret])

    # kind:
    # kept the same name as in SIAE and prescriber models.
    # The kind of a structure is refered as "mesure" for ASP
    kind = models.CharField(verbose_name=_("Type"), max_length=4, choices=KIND_CHOICES)

    # status:
    # Employee record cycle of life:
    # - New: newly created
    # - Complete: all required fields are present to generate a JSON outpout
    # - Sent: When complete, JSON export can be sent to ASP
    # - Refused: For any reason reject by ASP, can be updated and submited again
    # - Processed: Sent to ASP and got positive feedback of processing by ASP. Can not be changed anymore
    status = models.CharField(verbose_name=_("Etat"), max_length=10, choices=STATUS_CHOICES, default=STATUS_NEW)

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

    financial_annex = models.ForeignKey(FinancialAnnex, on_delete=models.CASCADE)
    eligibility_diagnosis = models.ForeignKey(EligibilityDiagnosis, on_delete=models.CASCADE)
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
    employee = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        verbose_name = _("Fiche salarié")
        # An Employee record is unique for a given SIRET and Approval (number)
        unique_together = ("siret", "approval")

    def __str__(self):
        return f"{self.siret}={self.approval.number}"

    def save(self, *args, **kwargs):
        # Employee record can't be updated anymore if in "final " status
        # ToBeDiscussed: maybe exceptions are a bit to hard for model errors...
        if not self.is_updatable:
            raise RuntimeError(_("Cette fiche salarié est historisée et non-modifiable"))

        if self.pk:
            self.updated_at = timezone.now()
        return super.save(*args, **kwargs)

    @property
    def is_updatable(self):
        """
        Once in final state an EmployeeRecord is not updatable anymore.
        See save() method
        """
        return not (self.status == self.kind.STATUS_PROCESSED and self.json is not None)

    @property
    def set_complete(self):
        pass
