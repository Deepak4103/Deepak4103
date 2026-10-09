from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.AppLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("password/", views.password_change, name="password_change"),
    path("faculty/", views.faculty_list, name="faculty_list"),
    path("faculty/upload/", views.faculty_upload, name="faculty_upload"),
    path("faculty/template.<str:fmt>", views.faculty_template, name="faculty_template"),
    path("faculty/add/", views.faculty_add, name="faculty_add"),
    path("faculty/<int:pk>/edit/", views.faculty_edit, name="faculty_edit"),
    path("faculty/<int:pk>/reset/", views.faculty_reset_password, name="faculty_reset_password"),
    path("faculty/<int:pk>/toggle/", views.faculty_toggle_active, name="faculty_toggle_active"),
]
