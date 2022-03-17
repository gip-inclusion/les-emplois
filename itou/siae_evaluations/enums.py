from itou.siaes.models import Siae


class EvaluationChosenPercent:
    MIN = 20
    DEFAULT = 30
    MAX = 40


class EvaluationSiaesKind:
    # Siae.KIND_AI will be eligible for Evaluation from 2022
    Evaluable = [Siae.KIND_EI, Siae.KIND_ACI, Siae.KIND_ETTI]
