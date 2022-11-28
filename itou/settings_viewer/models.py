from django.db import models


class Setting(models.Model):
    """Placeholder model without database table, but with django admin page"""

    class Meta:
        managed = False  # not in Django's database
        default_permissions = ()
        permissions = [["view", "Access admin page"]]
