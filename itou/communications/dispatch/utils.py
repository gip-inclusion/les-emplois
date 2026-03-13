class JobSeekerNotification:
    def is_manageable_by_user(self):
        return super().is_manageable_by_user() and self.user.is_job_seeker


class EmployerNotification:
    def is_manageable_by_user(self):
        return super().is_manageable_by_user() and self.user.is_employer


class PrescriberNotification:
    def is_manageable_by_user(self):
        return super().is_manageable_by_user() and self.user.is_prescriber


class PrescriberOrEmployerNotification:
    def is_manageable_by_user(self):
        return super().is_manageable_by_user() and self.user.is_caseworker


class PrescriberOrEmployerOrLaborInspectorNotification:
    def is_manageable_by_user(self):
        return super().is_manageable_by_user() and self.user.is_professional


class WithOrganizationMixin:
    def is_manageable_by_user(self):
        return super().is_manageable_by_user() and self.organization is not None
