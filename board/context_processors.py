from .views import common_context

def course_context(request):
    context = common_context()
    if request.user.is_authenticated:
        from .auth_views import uses_default_password
        context["notifications_unread_count"] = request.user.notifications.filter(read_at__isnull=True).count()
        context["uses_default_password"] = uses_default_password(request)
    return context
