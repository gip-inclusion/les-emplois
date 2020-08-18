from django.shortcuts import render


def stats(request, template_name="stats/stats.html"):
    return render(request, template_name)
