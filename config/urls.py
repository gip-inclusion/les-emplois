from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views import defaults as default_views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('siae/', include('itou.siae.urls')),
    path('accounts/', include('allauth.urls')),
]

if settings.DEBUG and 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [path('__debug__/', include(debug_toolbar.urls))] + urlpatterns
