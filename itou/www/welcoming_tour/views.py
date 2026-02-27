from django.shortcuts import render


def index(request):
    user = request.user
    template_name = "welcoming_tour/job_seeker.html"

    # FIXME: We probably want to display thewelcoming tour again
    # when joining a company for the first time ?
    if request.from_employer:
        template_name = "welcoming_tour/employer.html"

    if request.from_prescriber:
        template_name = "welcoming_tour/prescriber.html"

    user.has_completed_welcoming_tour = True
    user.save()

    return render(request, template_name)
