import ipaddress
from datetime import timedelta
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.http import HttpResponseRedirect
from django.utils import timezone
from .models import LoginAttempt

def _validated_ip(value):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None

def client_ip(request):
    remote_ip = _validated_ip(request.META.get("REMOTE_ADDR"))
    if remote_ip and ipaddress.ip_address(remote_ip).is_loopback:
        return _validated_ip(request.META.get("HTTP_X_REAL_IP")) or remote_ip
    return remote_ip

class ThrottledLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True
    window = timedelta(minutes=15)
    max_failures = 5
    # Cap on failures from one IP across all accounts: stops an outside script
    # from walking the student-ID list 5 guesses at a time. Set well above what
    # a classroom behind one campus NAT produces by mistyping.
    max_ip_failures = 50
    def post(self, request, *args, **kwargs):
        username = User.normalize_username(request.POST.get("username", "").strip())[:150]
        ip = client_ip(request)
        since = timezone.now() - self.window
        recent = LoginAttempt.objects.filter(username=username, ip_address=ip, created_at__gte=since)
        if recent.count() >= self.max_failures or LoginAttempt.objects.filter(ip_address=ip, created_at__gte=since).count() >= self.max_ip_failures:
            form = self.get_form(); form.add_error(None, "登录尝试过多，请稍后再试。"); return self.form_invalid(form)
        response = super().post(request, *args, **kwargs)
        if 300 <= response.status_code < 400 and request.user.is_authenticated: recent.delete()
        else: LoginAttempt.objects.create(username=username, ip_address=ip)
        return response

class AdminThrottledLoginView(ThrottledLoginView):
    authentication_form = AdminAuthenticationForm
    template_name = "admin/login.html"
    redirect_authenticated_user = False
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_staff:
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)
    def get_context_data(self, **kwargs):
        return admin.site.each_context(self.request) | super().get_context_data(**kwargs)

DEFAULT_PASSWORD_SESSION_KEY = "uses_default_password"

def uses_default_password(request):
    """Checked once per session (a password hash costs ~100 ms), then cached in the session."""
    if DEFAULT_PASSWORD_SESSION_KEY not in request.session:
        request.session[DEFAULT_PASSWORD_SESSION_KEY] = request.user.check_password(request.user.username)
    return request.session[DEFAULT_PASSWORD_SESSION_KEY]

class TrackedPasswordChangeView(PasswordChangeView):
    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session[DEFAULT_PASSWORD_SESSION_KEY] = self.request.user.check_password(self.request.user.username)
        return response
