from django.urls import path

from . import views

urlpatterns = [
    path("classes/<int:class_pk>/timetable/", views.timetable_list, name="timetable_list"),
    path("classes/<int:class_pk>/timetable/upload/", views.timetable_upload, name="timetable_upload"),
    path("classes/<int:class_pk>/timetable/new/", views.timetable_new, name="timetable_new"),
    path("timetable/template.<str:fmt>", views.template_download, name="timetable_template"),
    path("timetable/<int:pk>/", views.timetable_grid, name="timetable_grid"),
    path("timetable/<int:pk>/delete/", views.timetable_delete, name="timetable_delete"),
]
