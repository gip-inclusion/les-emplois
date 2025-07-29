import logging


logger = logging.getLogger(__name__)


class Sentinel:
    """Class to be used for sentinel object, but the object will be falsy"""

    def __bool__(self):
        return False
