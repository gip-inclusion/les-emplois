import json
import logging
import traceback

from django.core.exceptions import DisallowedHost
from django.http import HttpResponse
from django.utils import timezone


logger = logging.getLogger("probe")


class LogDisallowedHostMiddleware:
    """Logs full forensic details for Clever Cloud / proxy probes BEFORE Django rejects the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Trigger host validation here so we can log details before Django's
        # BaseHandler converts DisallowedHost into a 400 response (which would
        # swallow the exception before any outer except clause could see it).
        try:
            request.get_host()
        except DisallowedHost as exc:
            self.log_probe(request, exc)
            return HttpResponse("probe ok", status=200)
        return self.get_response(request)

    def log_probe(self, request, exc):
        meta = request.META

        data = {
            "timestamp": timezone.now().isoformat(),
            "event": "DISALLOWED_HOST_PROBE",
            # request line
            "method": request.method,
            "path": request.get_full_path(),
            "scheme": request.scheme,
            # network
            "remote_addr": meta.get("REMOTE_ADDR"),
            "server_addr": meta.get("SERVER_NAME"),
            "server_port": meta.get("SERVER_PORT"),
            # host headers
            "http_host": meta.get("HTTP_HOST"),
            "x_forwarded_host": meta.get("HTTP_X_FORWARDED_HOST"),
            "x_forwarded_for": meta.get("HTTP_X_FORWARDED_FOR"),
            "x_forwarded_proto": meta.get("HTTP_X_FORWARDED_PROTO"),
            "forwarded": meta.get("HTTP_FORWARDED"),
            # probe fingerprinting
            "user_agent": meta.get("HTTP_USER_AGENT"),
            "accept": meta.get("HTTP_ACCEPT"),
            # clever / proxy headers often present
            "x_request_id": meta.get("HTTP_X_REQUEST_ID"),
            "x_real_ip": meta.get("HTTP_X_REAL_IP"),
            "x_forwarded_port": meta.get("HTTP_X_FORWARDED_PORT"),
            # uwsgi / nginx info
            "uwsgi_vars": {k: v for k, v in meta.items() if k.startswith("UWSGI") or k.startswith("uwsgi")},
            # FULL HEADERS DUMP
            "all_http_headers": {k: v for k, v in meta.items() if k.startswith("HTTP_")},
            # raw environ snapshot
            "wsgi_environ_keys": sorted(list(meta.keys())),
            "exception": str(exc),
            "traceback": traceback.format_exc(),
        }

        logger.warning("\n\n\nCLEVER_PROBE_LOG %s", json.dumps(data, indent=2, default=repr))
