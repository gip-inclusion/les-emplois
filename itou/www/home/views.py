from django.contrib.auth.decorators import login_not_required

from itou.utils.readonly import readonly_view
from itou.www.dashboard import views as dashboard_views
from itou.www.search_views import views as search_views


@login_not_required
@readonly_view
def home(request):
    if request.user.is_authenticated:
        return dashboard_views.dashboard(request)
    return search_views.search_home(request)
