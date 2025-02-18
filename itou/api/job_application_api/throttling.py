from rest_framework import throttling


class JobApplicationSearchThrottle(throttling.SimpleRateThrottle):
    scope = "job-applications-search"

    def get_cache_key(self, request, view):
        if not request.auth:
            return None

        return self.cache_format % {
            "scope": self.scope,
            "ident": request.auth.department,
        }
