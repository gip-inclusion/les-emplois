from django.shortcuts import render


def details(request, template_name='siae/details.html'):
    context = {}
    return render(request, template_name, context)
