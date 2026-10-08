from django.urls import include, path

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("academics.urls")),
    path("", include("timetable.urls")),
    path("", include("attendance.urls")),
]
