from csp.context_processors import nonce
from django.http import HttpResponseServerError
from django.template import TemplateDoesNotExist, loader
from django.views.decorators.csrf import requires_csrf_token
from django.views.defaults import ERROR_500_TEMPLATE_NAME, ERROR_PAGE_TEMPLATE

from itou.utils.settings_context_processors import expose_settings


@requires_csrf_token
def server_error(request, template_name=ERROR_500_TEMPLATE_NAME):
    try:
        template = loader.get_template(template_name)
    except TemplateDoesNotExist:
        if template_name != ERROR_500_TEMPLATE_NAME:
            # Reraise if it's a missing custom template.
            raise
        return HttpResponseServerError(
            ERROR_PAGE_TEMPLATE % {"title": "Server Error (500)", "details": ""},
        )
    try:
        # Those two context processors are needed for layout/base.html
        context = expose_settings(request) | nonce(request)
    except Exception:
        # This shouldn't happen, but we really don't want the error page to also crash
        context = {}
    return HttpResponseServerError(template.render(context))
