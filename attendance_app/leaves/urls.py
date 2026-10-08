from django.urls import path

from . import views

urlpatterns = [
    path("leave/", views.my_leaves, name="my_leaves"),
    path("leave/apply/", views.leave_apply, name="leave_apply"),
    path("leaves/new/", views.leave_apply, name="leave_new_admin"),
    path("leaves/", views.leave_list, name="leave_list"),
    path("leaves/unadjusted/", views.unadjusted, name="unadjusted"),
    path("leaves/balances/", views.balances, name="leave_balances"),
    path("leaves/<int:pk>/", views.leave_detail, name="leave_detail"),
    path("leaves/<int:pk>/adjust/", views.leave_adjust, name="leave_adjust"),
    path("leaves/<int:pk>/cancel/", views.leave_cancel, name="leave_cancel"),
    path("leaves/<int:pk>/decide/", views.leave_decide, name="leave_decide"),
    path("leaves/<int:pk>/return/", views.return_offer, name="return_offer"),
    path("adjustments/<int:pk>/clear/", views.adjustment_clear, name="adjustment_clear"),
    path("adjustments/<int:pk>/respond/", views.adjustment_respond, name="adjustment_respond"),
    path("notifications/clear/", views.notifications_clear, name="notifications_clear"),
    path("leave-types/", views.leave_type_list, name="leave_type_list"),
    path("leave-types/add/", views.leave_type_edit, name="leave_type_add"),
    path("leave-types/<int:pk>/edit/", views.leave_type_edit, name="leave_type_edit"),
    path("leave-types/<int:pk>/delete/", views.leave_type_delete, name="leave_type_delete"),
]
