from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class EmployeeRecordConfig(AppConfig):
    name = "itou.employee_record"
    verbose_name = _("Fiches salarié")
