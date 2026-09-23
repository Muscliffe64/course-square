from django.contrib import admin
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.template.response import TemplateResponse
from django.urls import path
from .forms import PostAdminForm
from .models import Announcement, Comment, Like, LoginAttempt, Notification, Post, PostImage, Report, Resource, VisitLog

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    form = PostAdminForm
    list_display = ("title", "kind", "author", "anonymous", "status", "pinned", "created_at")
    list_filter = ("kind", "anonymous", "status", "pinned")


@admin.register(PostImage)
class PostImageAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "post", "is_cover", "created_at")
    list_filter = ("is_cover",)
    search_fields = ("original_filename", "post__title")
    readonly_fields = ("original_filename", "created_at")

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("post", "author", "anonymous", "created_at")

@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "created_at")

@admin.register(VisitLog)
class VisitLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "ip_address", "visitor", "path")
    list_filter = ("ip_address",)
    search_fields = ("ip_address", "path", "user__username", "user__first_name")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="访客")
    def visitor(self, obj):
        if not obj.user:
            return "未登录"
        return obj.user.first_name or obj.user.username

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [path("stats/", self.admin_site.admin_view(self.stats_view), name="board_visitlog_stats")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["stats_url"] = "stats/"
        return super().changelist_view(request, extra_context=extra_context)

    def stats_view(self, request):
        by_ip = VisitLog.objects.values("ip_address").annotate(visits=Count("id")).order_by("-visits")[:100]
        by_user = (VisitLog.objects.exclude(user=None).values("user__username", "user__first_name")
                   .annotate(visits=Count("id")).order_by("-visits")[:100])
        by_day = (VisitLog.objects.annotate(day=TruncDate("created_at")).values("day")
                  .annotate(visits=Count("id"), unique_ips=Count("ip_address", distinct=True)).order_by("-day")[:30])
        context = {
            **self.admin_site.each_context(request),
            "title": "访问统计",
            "by_ip": by_ip,
            "by_user": by_user,
            "by_day": by_day,
            "total": VisitLog.objects.count(),
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/board/visitlog_stats.html", context)

admin.site.register(Announcement); admin.site.register(Like); admin.site.register(Report); admin.site.register(LoginAttempt)
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "actor", "kind", "post", "created_at", "read_at")
    list_filter = ("kind", "read_at")
    search_fields = ("recipient__username", "recipient__first_name", "post__title")
    readonly_fields = ("recipient", "actor", "kind", "post", "comment", "created_at", "read_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
admin.site.site_header = "人工智能导论·课程管理"
admin.site.site_title = "课程管理"
admin.site.index_title = "内容与账号管理"
