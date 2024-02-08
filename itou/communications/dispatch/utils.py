__all__ = [
    "JobSeekerNotification",
    "EmployerNotification",
    "PrescriberNotification",
    "PrescriberOrEmployerNotification",
]


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
        return super().is_manageable_by_user() and any([self.user.is_prescriber, self.user.is_employer])
