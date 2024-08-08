import logging

from django.http import HttpResponseServerError
from django.template import TemplateDoesNotExist, engines, loader
from django.views.decorators.csrf import requires_csrf_token
from django.views.defaults import ERROR_500_TEMPLATE_NAME, ERROR_PAGE_TEMPLATE


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
    [template_backend] = engines.all()
    context = {}
    try:
        for context_processor in template_backend.engine.template_context_processors:
            context |= context_processor(request)
    except Exception:
        # This shouldn't happen, but we really don't want the error page to also crash
        logging.getLogger("itou.www").exception("Unable to create error page context.")
        context = {}
    return HttpResponseServerError(template.render(context))
