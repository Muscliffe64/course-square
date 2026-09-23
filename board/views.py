import re
from datetime import timedelta
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme
from .forms import CommentForm, PlanForm, PostForm, QuickPostForm, ReportForm
from .feed import course_feed_page
from .media import video_embed_url
from .models import Announcement, Comment, Lecture, Like, Notification, Post, PostImage, Resource, Ticket
from .pending import derive_title, pending_comments, pending_posts

IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
}
# Per-image URLs never change content (a replaced image gets a fresh thumbnail
# and at most one day of staleness), so the browser may keep them. "private"
# keeps shared proxies out; HTML pages stay no-store.
PRIVATE_MEDIA_CACHE = "private, max-age=86400"

def healthz(request):
    return HttpResponse("ok", content_type="text/plain")

def common_context():
    today = timezone.localdate()
    return {"announcements": Announcement.objects.filter(active=True), "current_week_start": today - timedelta(days=today.weekday())}

@login_required
def home(request):
    kind, sort, week = request.GET.get("kind", ""), request.GET.get("sort", "new"), request.GET.get("week", "all")
    if sort not in {"new", "popular"}: sort = "new"
    if week not in {"all", "current"}: week = "all"
    if kind not in {*Post.Kind.values, "resource"}: kind = ""
    context = common_context()
    page = course_feed_page(kind, sort, context["current_week_start"] if week == "current" else None, request.GET.get("page"))
    context.update({"page_obj": page, "kind": kind, "sort": sort, "week": week, "topic_count": Post.objects.filter(kind="topic").count(), "showcase_count": Post.objects.filter(kind="showcase").count(), "resource_count": Resource.objects.count()})
    if kind != "resource":
        context["quick_draft"] = request.session.pop("quick_draft", None)
        context["quick_kind"] = kind or Post.Kind.TOPIC
        context["ticket_lecture"] = Lecture.latest_held()
    # 右栏热榜在首页各标签都显示；窄屏的内联版本由模板决定只在哪些视图出现。
    context.update(topic_ranking(request.user))
    return render(request, "board/home.html", context)

RANKING_SIZE = 8
NEW_CANDIDATE_AGE = timedelta(hours=24)

def topic_ranking(user):
    """「下节课想听什么」排行：还开放、没排进讲次的提问，按赞同数排序。赞同 = 投票。"""
    upcoming = Lecture.upcoming()
    candidates = list(Post.objects.filter(kind=Post.Kind.TOPIC, status=Post.Status.OPEN, planned_lecture__isnull=True)
                      .annotate(like_count=Count("likes", distinct=True))
                      .order_by("-like_count", "-created_at")[:RANKING_SIZE])
    liked = set(Like.objects.filter(user=user, post__in=candidates).values_list("post_id", flat=True))
    top = candidates[0].like_count if candidates else 0
    fresh_since = timezone.now() - NEW_CANDIDATE_AGE
    for post in candidates:
        post.voted = post.pk in liked
        post.is_new = post.created_at >= fresh_since
        post.percent = round(post.like_count * 100 / top) if top else 0
    leaders = [post for post in candidates if top and post.like_count == top]
    return {"show_ranking": True, "ranking": candidates, "ranking_upcoming": upcoming, "ranking_tie": len(leaders) > 1,
            "ranking_voters": Like.objects.filter(post__kind=Post.Kind.TOPIC, post__status=Post.Status.OPEN, post__planned_lecture__isnull=True).values("user").distinct().count()}

QUICK_DUPLICATE_WINDOW = timedelta(seconds=30)

@login_required
@require_POST
def quick_post(request):
    form = QuickPostForm(request.POST)
    tab = request.POST.get("tab") if request.POST.get("tab") in Post.Kind.values else ""
    back = reverse("board:home") + (f"?kind={tab}" if tab else "")
    if not form.is_valid():
        mode = request.POST.get("mode") if request.POST.get("mode") in {"topic", "showcase", "teacher"} else ""
        request.session["quick_draft"] = {"body": request.POST.get("body", "")[:1000], "anonymous": bool(request.POST.get("anonymous")), "mode": mode}
        messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
        return redirect(back)
    data = form.cleaned_data
    mode = request.POST.get("mode", "")
    if mode == "teacher":
        data["to_teacher"] = True
    elif mode in Post.Kind.values:
        data["kind"] = mode
    recent = timezone.now() - QUICK_DUPLICATE_WINDOW
    if data["to_teacher"] and not request.user.is_staff:
        lecture = Lecture.latest_held()
        # 双击或刷新重复提交：同一内容 30 秒内只记一次。
        if not Ticket.objects.filter(author=request.user, body=data["body"], created_at__gte=recent).exists():
            Ticket.objects.create(author=request.user, lecture=lecture, body=data["body"])
        messages.success(request, f"已实名交给老师{('（' + lecture.label + '的课后小票）') if lecture else ''}。只有老师能看到，老师会在课上统一回应。")
        return redirect(back)
    post = Post.objects.filter(author=request.user, body=data["body"], kind=data["kind"], anonymous=data["anonymous"], created_at__gte=recent).first()
    if post is None:
        post = Post.objects.create(author=request.user, kind=data["kind"], title=derive_title(data["body"]), body=data["body"], anonymous=data["anonymous"])
    messages.success(request, "已发布，它已经是「想听热榜」的候选，有人点 ♥ 就会往上排。" if post.kind == Post.Kind.TOPIC else "已发布。")
    return redirect(back + f"#post-{post.pk}")

@login_required
@require_POST
def post_plan(request, pk):
    if not request.user.is_staff:
        raise PermissionDenied
    post = get_object_or_404(Post, pk=pk)
    form = PlanForm(request.POST)
    lecture_id = form.cleaned_data["lecture"] if form.is_valid() else None
    lecture = get_object_or_404(Lecture, pk=lecture_id) if lecture_id else None
    previous = post.planned_lecture_id
    post.planned_lecture = lecture
    if lecture:
        post.status = Post.Status.PLANNED
    elif post.status == Post.Status.PLANNED:
        post.status = Post.Status.OPEN
    post.save(update_fields=["planned_lecture", "status"])
    if lecture and lecture.pk != previous and post.author_id != request.user.id:
        Notification.objects.create(recipient=post.author, actor=request.user, kind=Notification.Kind.POST_PLANNED, post=post)
    messages.success(request, f"已排进{lecture.label}，作者会收到通知。" if lecture else "已取消排课。")
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect("board:post_detail", pk=pk)

def _staff_only(user):
    if not user.is_staff:
        raise PermissionDenied

@login_required
def pending(request):
    _staff_only(request.user)
    ticket_lecture = Lecture.latest_held()
    tickets = Ticket.objects.filter(lecture=ticket_lecture) if ticket_lecture else Ticket.objects.none()
    return render(request, "board/pending.html", common_context() | {
        "pending_post_list": pending_posts(), "pending_comment_list": pending_comments(),
        "ticket_lecture": ticket_lecture, "ticket_count": tickets.count(),
        "upcoming_lecture": Lecture.upcoming(), "now": timezone.now(),
    })

@login_required
@require_POST
def pending_dismiss(request):
    _staff_only(request.user)
    model = {"post": Post, "comment": Comment}.get(request.POST.get("type"))
    object_id = request.POST.get("id", "")
    if model is None or not object_id.isdigit():
        raise Http404
    model.objects.filter(pk=int(object_id)).update(teacher_dismissed=True)
    anchor = request.POST.get("anchor", "")
    return redirect(reverse("board:pending") + (f"#{anchor}" if re.fullmatch(r"[a-z]+-\d+", anchor) else ""))

@login_required
def post_create(request):
    initial_kind = request.GET.get("kind") if request.GET.get("kind") in dict(Post.Kind.choices) else None
    form = PostForm(request.POST or None, request.FILES or None, initial={"kind": initial_kind} if initial_kind else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            post = form.save(commit=False); post.author = request.user; post.save()
            form.save_gallery(post)
        messages.success(request, "已发布。")
        return redirect("board:post_detail", pk=post.pk)
    return render(request, "board/post_form.html", common_context() | {"form": form})

@login_required
def post_edit(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if not _can_delete(request.user, post):
        raise PermissionDenied
    form = PostForm(request.POST or None, request.FILES or None, instance=post)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            post = form.save()
            form.save_gallery(post)
        messages.success(request, "已更新。")
        return redirect("board:post_detail", pk=post.pk)
    return render(request, "board/post_form.html", common_context() | {"form": form, "post": post})

@login_required
def post_detail(request, pk):
    post = get_object_or_404(Post.objects.select_related("author", "planned_lecture").prefetch_related("gallery_images").annotate(like_count=Count("likes", distinct=True), comment_count=Count("comments", distinct=True)), pk=pk)
    reply_to = request.GET.get("reply_to")
    initial = {"parent_id": reply_to} if reply_to and reply_to.isdigit() and post.comments.filter(pk=reply_to).exists() else {}
    staff_extra = {"lectures": Lecture.objects.all(), "upcoming_lecture": Lecture.upcoming()} if request.user.is_staff else {}
    return render(request, "board/post_detail.html", common_context() | staff_extra | {"post": post, "comments": post.comments.select_related("author", "parent"), "liked": post.likes.filter(user=request.user).exists(), "comment_form": CommentForm(initial=initial), "report_form": ReportForm(), "video_embed_url": video_embed_url(post.video_link)})

def _can_delete(user, obj): return user.is_staff or obj.author_id == user.id

@login_required
def post_delete(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if not _can_delete(request.user, post): raise PermissionDenied
    if request.method == "POST":
        post.delete(); messages.success(request, "已删除。"); return redirect("board:home")
    return render(request, "board/confirm_delete.html", common_context() | {"object": post, "cancel_url": reverse("board:post_detail", args=[post.pk])})

@login_required
@require_POST
def post_like(request, pk):
    post = get_object_or_404(Post, pk=pk)
    like, created = Like.objects.get_or_create(post=post, user=request.user)
    if created and post.author_id != request.user.id:
        Notification.objects.get_or_create(recipient=post.author, actor=request.user, kind=Notification.Kind.POST_LIKE, post=post)
    if not created: like.delete()
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect("board:post_detail", pk=pk)

@login_required
@require_POST
@transaction.atomic
def comment_create(request, pk):
    post = get_object_or_404(Post, pk=pk); form = CommentForm(request.POST)
    if form.is_valid():
        parent_id = form.cleaned_data.get("parent_id")
        parent = get_object_or_404(Comment, pk=parent_id, post=post) if parent_id else None
        comment = form.save(commit=False); comment.post = post; comment.author = request.user; comment.parent = parent; comment.save()
        if parent and parent.author_id != request.user.id:
            Notification.objects.create(recipient=parent.author, actor=request.user, actor_anonymous=comment.anonymous, kind=Notification.Kind.COMMENT_REPLY, post=post, comment=comment)
        if not request.user.is_staff:
            Notification.objects.bulk_create([
                Notification(recipient=staff, actor=request.user, actor_anonymous=comment.anonymous, kind=Notification.Kind.NEW_COMMENT, post=post, comment=comment)
                for staff in User.objects.filter(is_staff=True, is_active=True).exclude(pk=request.user.pk).exclude(pk=parent.author_id if parent else None)
            ])
    else: messages.error(request, "评论内容无效。")
    return redirect("board:post_detail", pk=pk)

@login_required
def comment_delete(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    if not _can_delete(request.user, comment): raise PermissionDenied
    if request.method == "POST":
        post_id = comment.post_id; comment.delete(); return redirect("board:post_detail", pk=post_id)
    return render(request, "board/confirm_delete.html", common_context() | {"object": comment, "cancel_url": reverse("board:post_detail", args=[comment.post_id])})

@login_required
def resources(request): return render(request, "board/resources.html", common_context() | {"resources": Resource.objects.select_related("lecture")})

@login_required
def resource_download(request, pk):
    resource = get_object_or_404(Resource, pk=pk)
    response = FileResponse(resource.file.open("rb"), as_attachment=True, filename=resource.original_filename or "resource")
    response["X-Content-Type-Options"] = "nosniff"; return response

@login_required
def resource_read(request, pk):
    from markdown_it import MarkdownIt
    from .models import MAX_MARKDOWN_READ_BYTES
    resource = get_object_or_404(Resource, pk=pk)
    if not resource.is_markdown:
        return redirect("board:resource_download", pk=pk)
    if resource.file.size > MAX_MARKDOWN_READ_BYTES:
        messages.error(request, "文件过大，请下载后阅读。")
        return redirect("board:resources")
    text = resource.file.open("rb").read().decode("utf-8", errors="replace")
    html = MarkdownIt("gfm-like", {"html": False, "linkify": False, "breaks": True}).render(text)
    return render(request, "board/resource_read.html", common_context() | {"resource": resource, "content_html": html})

@login_required
def post_image(request, pk):
    post = get_object_or_404(Post, pk=pk)
    return _post_media_response(post.cover_image_file, post.cover_image_filename, IMAGE_CONTENT_TYPES)

@login_required
def post_gallery_image(request, post_pk, image_pk):
    image = get_object_or_404(PostImage, pk=image_pk, post_id=post_pk)
    return _cacheable(_post_media_response(image.image, image.original_filename, IMAGE_CONTENT_TYPES))

@login_required
def post_gallery_thumb(request, post_pk, image_pk):
    image = get_object_or_404(PostImage, pk=image_pk, post_id=post_pk)
    if not image.thumbnail:  # not generated yet: fall back to the original
        return _cacheable(_post_media_response(image.image, image.original_filename, IMAGE_CONTENT_TYPES))
    name = Path(image.original_filename or "image").stem + Path(image.thumbnail.name).suffix
    return _cacheable(_post_media_response(image.thumbnail, name, IMAGE_CONTENT_TYPES))

def _cacheable(response):
    response["Cache-Control"] = PRIVATE_MEDIA_CACHE
    response.private_media_cache = True  # read by PrivateDynamicResponseMiddleware
    return response

@login_required
def post_audio(request, pk):
    post = get_object_or_404(Post, pk=pk)
    return _post_media_response(post.audio, post.audio_filename, {
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg",
    })

def _post_media_response(upload, filename, content_types):
    if not upload:
        raise Http404
    try:
        media_file = upload.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    response = FileResponse(media_file, filename=filename, content_type=content_types.get(
        Path(filename).suffix.lower(), "application/octet-stream",
    ))
    response["X-Content-Type-Options"] = "nosniff"
    return response

@login_required
@require_POST
def report_post(request, pk):
    post = get_object_or_404(Post, pk=pk); form = ReportForm(request.POST)
    if form.is_valid():
        report = form.save(commit=False); report.post = post; report.reporter = request.user; report.save(); messages.success(request, "已提交举报。")
    return redirect("board:post_detail", pk=pk)

@login_required
def settings_view(request):
    return render(request, "board/settings.html", common_context() | {"using_default_password": request.user.check_password(request.user.username)})

@login_required
def notifications(request):
    items = request.user.notifications.select_related("actor", "post__planned_lecture", "comment")
    return render(request, "board/notifications.html", common_context() | {"notifications": Paginator(items, 30).get_page(request.GET.get("page"))})

@login_required
@require_POST
def notification_open(request, pk):
    item = get_object_or_404(Notification, pk=pk, recipient=request.user)
    request.user.notifications.filter(pk=pk, read_at__isnull=True).update(read_at=timezone.now())
    target = reverse("board:post_detail", args=[item.post_id])
    return redirect(target + (f"#comment-{item.comment_id}" if item.comment_id else ""))

@login_required
@require_POST
def notifications_read(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return redirect("board:notifications")
