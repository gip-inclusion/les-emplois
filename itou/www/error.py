import logging

from django.conf import settings
from django.http import HttpResponseServerError
from django.template import TemplateDoesNotExist, loader
from django.utils.module_loading import import_string
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
    [template_settings] = settings.TEMPLATES
    context_processors_path = template_settings["OPTIONS"]["context_processors"]
    context_processors = [import_string(processor_path) for processor_path in context_processors_path]
    context = {}
    try:
        for context_processor in context_processors:
            context |= context_processor(request)
    except Exception:
        # This shouldn't happen, but we really don't want the error page to also crash
        logging.getLogger("itou.www").exception("Unable to create error page context.")
        context = {}
    return HttpResponseServerError(template.render(context))
