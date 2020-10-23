from django.conf import settings


class ItouCurrentOrganizationMiddleware:
    """
    Store the ID of the current prescriber organization or employer structure in session.
    https://docs.djangoproject.com/en/dev/topics/http/middleware/#writing-your-own-middleware
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # Before the view is called.

        user = request.user

        if user.is_authenticated:

            if user.is_siae_staff:
                current_siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
                siae_set = user.siae_set
                if not siae_set.filter(pk=current_siae_pk).exists():
                    first_siae = (
                        siae_set.active().first() or siae_set.active_or_in_grace_period().first() or siae_set.first()
                    )
                    if first_siae:
                        request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = first_siae.pk

            elif user.is_prescriber:
                # Prescriber users can now select an organization
                # (if they are member of several prescriber organizations)
                if user.prescriberorganization_set.exists():
                    # Choose first prescriber organization for user if none is selected yet
                    # (f.i. after login)
                    request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = (
                        request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
                        or user.prescriberorganization_set.first().pk
                    )
                elif request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY):
                    # If the user is an "orienteur"
                    # => No need to track the current org in session (none)
                    # => Remove any old session entry if needed
                    del request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY]

        response = self.get_response(request)

        # After the view is called.

        return response
