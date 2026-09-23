from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from board.auth_views import AdminThrottledLoginView, ThrottledLoginView, TrackedPasswordChangeView
from board.views import healthz
urlpatterns = [
    path("", include("board.urls")),
    path("login/", ThrottledLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/change/", TrackedPasswordChangeView.as_view(), name="password_change"),
    path("password/change/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("admin/login/", AdminThrottledLoginView.as_view()),
    path("admin/", admin.site.urls), path("healthz/", healthz),
]
