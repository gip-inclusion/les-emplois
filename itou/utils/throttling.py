from itou.api import throttling


class FailSafeAnonRateThrottle(throttling.FailSafeAnonRateThrottle):
    rate = "30/minute"


class FailSafeUserRateThrottle(throttling.FailSafeUserRateThrottle):
    rate = "60/minute"
