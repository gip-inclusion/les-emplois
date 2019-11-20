from django.conf import settings


class ItouCurrentOrganizationMiddleware:
    """
    Store the ID of the current organization in session.
    https://docs.djangoproject.com/en/dev/topics/http/middleware/#writing-your-own-middleware
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # Before the view is called.

        user = request.user

        if user.is_authenticated:

            if user.is_siae_staff and user.siae_set.exists():
                current_siae_pk = request.session.get(
                    settings.ITOU_SESSION_CURRENT_SIAE_KEY
                )
                if current_siae_pk not in [s.pk for s in user.siae_set.all()]:
                    request.session[
                        settings.ITOU_SESSION_CURRENT_SIAE_KEY
                    ] = user.siae_set.first().pk

            elif user.is_prescriber and user.prescriberorganization_set.exists():
                request.session[
                    settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY
                ] = user.prescriberorganization_set.first().pk

        response = self.get_response(request)

        # After the view is called.

        return response
