from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.template.response import TemplateResponse
from django.urls import path
from .forms import PostAdminForm
from .models import Announcement, Comment, Lecture, Like, LoginAttempt, LoginEvent, Notification, Post, PostImage, Report, Resource, ResourceAccess, TeacherDigest, Ticket, VisitLog
from .participation import SORTS, participation, participation_xlsx
from .tickets import tickets_csv

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    form = PostAdminForm
    list_display = ("title", "kind", "author", "anonymous", "status", "planned_lecture", "pinned", "created_at")
    list_filter = ("kind", "anonymous", "status", "planned_lecture", "pinned", "teacher_dismissed")


@admin.register(Lecture)
class LectureAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "date", "start_time", "planned_count", "ticket_count")
    ordering = ("number",)
    actions = ["export_tickets"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_planned=Count("planned_posts", distinct=True), _tickets=Count("tickets", distinct=True))

    @admin.display(description="排进的提问", ordering="_planned")
    def planned_count(self, obj):
        return obj._planned

    @admin.display(description="课后小票", ordering="_tickets")
    def ticket_count(self, obj):
        return obj._tickets

    @admin.action(description="导出所选讲次的课后小票（姓名换代号，CSV）")
    def export_tickets(self, request, queryset):
        numbers = "-".join(str(n) for n in queryset.order_by("number").values_list("number", flat=True))
        return tickets_csv(Ticket.objects.filter(lecture__in=queryset), f"tickets-lecture-{numbers}.csv")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("lecture", "student", "body", "created_at", "response", "responded_at")
    list_select_related = ("author", "lecture")
    list_filter = ("lecture", "response")
    search_fields = ("body", "author__username", "author__first_name")
    date_hierarchy = "created_at"
    actions = ["export_selected"]

    @admin.display(description="学生", ordering="author__first_name")
    def student(self, obj):
        return obj.author.first_name or obj.author.username

    @admin.action(description="导出所选小票（姓名换代号，CSV）")
    def export_selected(self, request, queryset):
        return tickets_csv(queryset, "tickets.csv")

    def has_add_permission(self, request):
        return False


@admin.register(TeacherDigest)
class TeacherDigestAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "new_count", "total_count")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PostImage)
class PostImageAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "post", "is_cover", "created_at")
    list_filter = ("is_cover",)
    search_fields = ("original_filename", "post__title")
    readonly_fields = ("original_filename", "created_at")

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("post", "author", "anonymous", "teacher_dismissed", "created_at")
    list_filter = ("teacher_dismissed",)

@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("title", "lecture", "category", "created_at")
    list_filter = ("lecture",)

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
    list_display = ("recipient", "actor", "kind", "post", "ticket", "created_at", "read_at")
    list_filter = ("kind", "read_at")
    search_fields = ("recipient__username", "recipient__first_name", "post__title")
    readonly_fields = ("recipient", "actor", "kind", "post", "ticket", "comment", "created_at", "read_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LoginEvent)
class LoginEventAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "user", "student_name", "ip_address")
    list_select_related = ("user",)
    search_fields = ("user__username", "user__first_name", "ip_address")
    date_hierarchy = "created_at"

    @admin.display(description="姓名", ordering="user__first_name")
    def student_name(self, obj):
        return obj.user.first_name


@admin.register(ResourceAccess)
class ResourceAccessAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "user", "student_name", "resource", "kind")
    list_select_related = ("user", "resource")
    list_filter = ("kind", "resource__lecture", "resource")
    search_fields = ("user__username", "user__first_name", "resource__title")
    date_hierarchy = "created_at"

    @admin.display(description="姓名", ordering="user__first_name")
    def student_name(self, obj):
        return obj.user.first_name

    def get_urls(self):
        return [path("participation/", self.admin_site.admin_view(self.participation_view), name="board_participation")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, extra_context=(extra_context or {}) | {"participation_link": True})

    def participation_view(self, request):
        if not request.user.is_staff:  # admin_view 已经挡过一次，这里再明确一遍：只有老师能看
            raise PermissionDenied
        sort = request.GET.get("sort", "id")
        sort = sort if sort in SORTS else "id"
        only_never = request.GET.get("never") == "1"
        rows, lectures, held, summary = participation(sort, only_never)
        if request.GET.get("export") == "xlsx":
            return participation_xlsx(rows, lectures, held)
        return TemplateResponse(request, "admin/board/participation.html", {
            **self.admin_site.each_context(request),
            "title": "学生参与度", "opts": self.model._meta,
            "rows": rows, "lectures": lectures, "held_ids": {lecture.pk for lecture in held}, "held_count": len(held),
            "summary": summary, "sort": sort, "sorts": [(key, label) for key, (label, _) in SORTS.items()],
            "only_never": only_never,
        })


admin.site.site_header = "人工智能导论·课程管理"
admin.site.site_title = "课程管理"
admin.site.index_title = "内容与账号管理"
