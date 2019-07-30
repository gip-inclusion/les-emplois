from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views import defaults as default_views


urlpatterns = [

    path('admin/', admin.site.urls),

    # Order is important! Some `itou.accounts.urls` override `allauth.urls`
    # and the first match listed will have priority.
    path('accounts/', include('itou.accounts.urls')),
    path('accounts/', include('allauth.urls')),

    path('siae/', include('itou.siae.urls')),

]

if settings.DEBUG and 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [path('__debug__/', include(debug_toolbar.urls))] + urlpatterns
