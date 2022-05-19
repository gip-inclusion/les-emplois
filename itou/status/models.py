from django.db import models


class ProbeStatus(models.Model):
    name = models.TextField(unique=True)

    last_success_at = models.DateTimeField(null=True)
    last_success_info = models.TextField(null=True)

    last_failure_at = models.DateTimeField(null=True)
    last_failure_info = models.TextField(null=True)

    def is_success(self):
        if not self.last_success_at and not self.last_failure_at:
            return None  # For when the probe didn't run (yet), or when we simply don't know

        if not self.last_success_at:
            return False
        if not self.last_failure_at:
            return True

        return self.last_success_at > self.last_failure_at
