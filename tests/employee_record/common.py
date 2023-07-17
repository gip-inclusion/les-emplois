from io import StringIO

import pytest
from django.core import management

from tests.utils.test import TestCase


@pytest.mark.usefixtures("unittest_compatibility")
class ManagementCommandTestCase(TestCase):
    # Override as needed
    MANAGEMENT_COMMAND_NAME = None

    def call_command(self, management_command_name=None, *args, **kwargs):
        """Redirect standard outputs from management command to StringIO objects for testing purposes."""

        out = StringIO()
        err = StringIO()
        command = management_command_name or self.MANAGEMENT_COMMAND_NAME

        assert command, "Management command name must be provided"

        management.call_command(
            command,
            *args,
            stdout=out,
            stderr=err,
            **kwargs,
        )

        return out.getvalue(), err.getvalue()
