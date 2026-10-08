from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin-home/", views.admin_home, name="admin_home"),

    path("classes/", views.class_list, name="class_list"),
    path("classes/add/", views.class_add, name="class_add"),
    path("classes/<int:pk>/", views.class_detail, name="class_detail"),
    path("classes/<int:pk>/edit/", views.class_edit, name="class_edit"),
    path("classes/<int:pk>/delete/", views.class_delete, name="class_delete"),

    path("classes/<int:class_pk>/students/add/", views.student_add, name="student_add"),
    path("classes/<int:class_pk>/students/upload/", views.student_upload, name="student_upload"),
    path("students/template.<str:fmt>", views.student_template, name="student_template"),
    path("students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("students/<int:pk>/delete/", views.student_delete, name="student_delete"),

    path("classes/<int:class_pk>/subjects/add/", views.subject_add, name="subject_add"),
    path("subjects/<int:pk>/edit/", views.subject_edit, name="subject_edit"),
    path("subjects/<int:pk>/delete/", views.subject_delete, name="subject_delete"),
    path("classes/<int:class_pk>/allotment/", views.allotment, name="allotment"),

    path("holidays/", views.holiday_list, name="holiday_list"),
    path("holidays/add/", views.holiday_add, name="holiday_add"),
    path("holidays/<int:pk>/edit/", views.holiday_edit, name="holiday_edit"),
    path("holidays/<int:pk>/delete/", views.holiday_delete, name="holiday_delete"),
]
