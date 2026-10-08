from django.urls import path

from . import views

urlpatterns = [
    path("reports/", views.report_index, name="report_index"),
    path("reports/<slug:slug>/", views.report_view, name="report_view"),
]
