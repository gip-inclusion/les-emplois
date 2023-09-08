from django.db import models

from itou.job_applications.models import JobApplication
from itou.siaes.models import Siae
from itou.users.models import User


class EmploymentContract(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="employé")
    employer = models.ForeignKey(Siae, on_delete=models.CASCADE, verbose_name="employeur")
    # As long as the job application stays the main object make this ForeignKey not nullable
    job_application = models.ForeignKey(
        JobApplication,
        on_delete=models.CASCADE,
        verbose_name="candidature",
        related_name="employment_contracts",
    )

    class Meta:
        verbose_name = "contrat de travail"
        verbose_name_plural = "contrats de travail"

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return f"{self.job_seeker} ({self.employer})"
