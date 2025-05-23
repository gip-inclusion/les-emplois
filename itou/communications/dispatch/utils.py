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
        return super().is_manageable_by_user() and (self.user.is_prescriber or self.user.is_employer)


class PrescriberOrEmployerOrLaborInspectorNotification:
    def is_manageable_by_user(self):
        return super().is_manageable_by_user() and (
            self.user.is_prescriber or self.user.is_employer or self.user.is_labor_inspector
        )


class WithStructureMixin:
    def is_manageable_by_user(self):
        return super().is_manageable_by_user() and self.structure is not None
