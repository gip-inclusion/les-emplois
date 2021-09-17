from django.shortcuts import render
from django.views.decorators.cache import cache_page


@cache_page(60 * 60)  # 1 hour
def index(request, template_name="api/index.html"):
    """
    Render the home page for the API
    """

    return render(request, template_name)
