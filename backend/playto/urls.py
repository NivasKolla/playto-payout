from django.contrib import admin
from django.urls import path, include
from payout.views import home

urlpatterns = [
    path('', home),
    path("admin/", admin.site.urls),
    path("api/v1/", include("payout.urls")),
]
