from django.shortcuts import render


def index(request, template_name="api/index.html"):
    """
    Render the home page for the API
    """

    return render(request, template_name)
