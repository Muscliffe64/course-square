class PrivateDynamicResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(response, "private_media_cache", False):
            return response  # per-image media sets its own private, short-lived cache policy
        response["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response

class VisitLoggingMiddleware:
    """记录页面访问的 IP 与用户，供管理员在后台查看。静态资源、图片音频和健康检查不计入。"""
    SKIP_PREFIXES = ("/static/", "/healthz/")
    SKIP_URL_NAMES = {"post_image", "post_gallery_image", "post_gallery_thumb", "post_audio"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, "resolver_match", None)
        if (request.method in {"GET", "HEAD"} and not request.path.startswith(self.SKIP_PREFIXES)
                and not (match and match.url_name in self.SKIP_URL_NAMES)):
            try:
                from .auth_views import client_ip
                from .models import VisitLog
                user = request.user if request.user.is_authenticated else None
                VisitLog.objects.create(user=user, ip_address=client_ip(request), path=request.path[:300])
            except Exception:
                pass  # 记录失败不影响正常访问
        return response
