import logging
import operator
from functools import reduce


logger = logging.getLogger(__name__)


class Sentinel:
    """Class to be used for sentinel object, but the object will be falsy"""

    def __bool__(self):
        return False


def dotteditemgetter(*items):
    def g(obj):
        slicer = 0 if len(items) == 1 else slice(None)
        return tuple(reduce(operator.getitem, item.split("."), obj) for item in items)[slicer]

    return g
