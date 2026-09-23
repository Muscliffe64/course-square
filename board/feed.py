"""Combine course activity in SQL, loading full objects only for the current page."""
from django.core.paginator import Paginator
from django.db.models import BooleanField, Count, F, IntegerField, Value

from .models import Post, Resource


def course_feed_page(kind, sort, week_start, page_number):
    posts = Post.objects.all()
    resources = Resource.objects.all()
    if kind in Post.Kind.values:
        posts = posts.filter(kind=kind)
        resources = resources.none()
    elif kind == 'resource':
        posts = posts.none()
    if week_start is not None:
        posts = posts.filter(created_at__date__gte=week_start)
        resources = resources.filter(created_at__date__gte=week_start)

    fields = ('pk', 'created_at', 'feed_type', 'feed_pinned', 'feed_score')
    post_rows = posts.order_by().annotate(
        feed_type=Value('post'), feed_pinned=F('pinned'),
        feed_score=Count('likes', distinct=True) + Count('comments', distinct=True),
    ).values(*fields)
    resource_rows = resources.order_by().annotate(
        feed_type=Value('resource'), feed_pinned=Value(False, output_field=BooleanField()),
        feed_score=Value(0, output_field=IntegerField()),
    ).values(*fields)
    ordering = ['-feed_pinned']
    if sort == 'popular':
        ordering.append('-feed_score')
    ordering.extend(['-created_at', 'feed_type', '-pk'])
    rows = post_rows.union(resource_rows, all=True).order_by(*ordering)
    page = Paginator(rows, 20).get_page(page_number)
    records = list(page.object_list)
    post_ids = [row['pk'] for row in records if row['feed_type'] == 'post']
    resource_ids = [row['pk'] for row in records if row['feed_type'] == 'resource']
    post_objects = Post.objects.select_related('author', 'planned_lecture').prefetch_related('gallery_images').annotate(
        like_count=Count('likes', distinct=True), comment_count=Count('comments', distinct=True),
    ).in_bulk(post_ids)
    resource_objects = Resource.objects.select_related('lecture').in_bulk(resource_ids)
    objects = {'post': post_objects, 'resource': resource_objects}
    # A concurrent deletion should not make the whole page fail.
    page.object_list = [
        {row['feed_type']: objects[row['feed_type']][row['pk']]}
        for row in records if row['pk'] in objects[row['feed_type']]
    ]
    return page
