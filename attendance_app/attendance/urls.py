import datetime

from django.urls import path, register_converter

from . import views


class DateConverter:
    regex = r"\d{4}-\d{2}-\d{2}"

    def to_python(self, value):
        return datetime.date.fromisoformat(value)   # ValueError -> 404

    def to_url(self, value):
        return value.isoformat()


register_converter(DateConverter, "date")

urlpatterns = [
    path("faculty-home/", views.faculty_home, name="faculty_home"),
    path("mark/<int:class_pk>/<date:date>/<int:period>/", views.mark_attendance, name="mark_attendance"),
    path("attendance/<int:pk>/", views.session_detail, name="session_detail"),
    path("attendance/<int:pk>/unlock/", views.session_unlock, name="session_unlock"),
    path("records/", views.records, name="records"),
    path("monitor/", views.monitor, name="monitor"),
]
