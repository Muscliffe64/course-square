"""教师「待回应」：学生发了东西，老师还没接话的内容。

帖子：学生发的、还开放、没排进讲次、老师没在下面留过言、没被标记「无需回复」。
留言：学生写的、没被标记「无需回复」、之后同一帖子下没有老师留言。
老师在帖子下留言、把帖子排进某一讲、或点「无需回复」，这一条就会从列表里消失。
"""
from django.db.models import Count, Exists, OuterRef

from .models import Comment, Post, Ticket


def pending_tickets():
    return Ticket.objects.filter(response="").select_related("author", "lecture").order_by("created_at")


def pending_posts():
    staff_comment = Comment.objects.filter(post=OuterRef("pk"), author__is_staff=True)
    return (Post.objects.filter(author__is_staff=False, status=Post.Status.OPEN, planned_lecture__isnull=True, teacher_dismissed=False)
            .exclude(Exists(staff_comment))
            .select_related("author")
            .annotate(like_count=Count("likes", distinct=True))
            .order_by("created_at"))


def pending_comments():
    later_staff_comment = Comment.objects.filter(
        post=OuterRef("post"), author__is_staff=True, created_at__gt=OuterRef("created_at"))
    return (Comment.objects.filter(author__is_staff=False, teacher_dismissed=False)
            .exclude(Exists(later_staff_comment))
            .select_related("author", "post", "parent__author")
            .order_by("created_at"))


def pending_counts():
    return {"posts": pending_posts().count(), "comments": pending_comments().count(), "tickets": pending_tickets().count()}


def new_after(last_post_id, last_comment_id, last_ticket_id):
    """上次推送之后新出现、且仍待回应的内容（用于站外提醒）。"""
    return (list(pending_posts().filter(pk__gt=last_post_id)), list(pending_comments().filter(pk__gt=last_comment_id)),
            list(Ticket.objects.filter(pk__gt=last_ticket_id).values_list("pk", flat=True)))


def max_ids():
    from django.db.models import Max
    return tuple(model.objects.aggregate(m=Max("pk"))["m"] or 0 for model in (Post, Comment, Ticket))


def derive_title(body, limit=30):
    """一行发帖没有标题：取第一句话，超过 limit 个字就截断。"""
    body = body.strip()
    ends = [i for i in (body.find(mark) for mark in "。！？!?\n") if i > 0]
    first = body[:min(ends) + 1] if ends else body
    text = " ".join(first.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
