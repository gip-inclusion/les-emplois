import logging


class DeprecatedLoggerMixin:
    """
    A mixin used to inject deprecated logger stuff in some of our old management commands.

    Do *not* use it for new commands! Use directly `self.stdout.write()` instead.
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
