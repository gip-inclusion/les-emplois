import logging

from django.core.management.base import BaseCommand


class ItouBaseCommand(BaseCommand):
    """
    A generic class for management commands, gathering all shared stuff (loggers etc).
    """

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity is not None and verbosity >= 1:
            self.logger.setLevel(logging.DEBUG)
