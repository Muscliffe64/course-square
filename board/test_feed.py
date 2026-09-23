import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Post, Resource


class CourseFeedTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        cls.media_settings = override_settings(MEDIA_ROOT=media.name)
        cls.media_settings.enable()
        cls.addClassCleanup(cls.media_settings.disable)

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('feed-student', first_name='学生')
        cls.topic = Post.objects.create(author=cls.student, title='选题卡片', body='问题', kind='topic')
        cls.share = Post.objects.create(author=cls.student, title='分享卡片', body='分享', kind='showcase')
        cls.resource = Resource.objects.create(title='讲义卡片', description='讲义说明', file=SimpleUploadedFile('lesson.md', b'# Lesson'))

    def setUp(self):
        self.client.force_login(self.student)

    def test_home_shows_resources_with_read_links_even_when_older_than_week(self):
        Resource.objects.filter(pk=self.resource.pk).update(created_at=timezone.now() - timedelta(days=14))
        response = self.client.get('/')
        self.assertContains(response, '讲义卡片')
        self.assertContains(response, reverse('board:resource_read', args=[self.resource.pk]))
        self.assertContains(response, reverse('board:resource_download', args=[self.resource.pk]))
        self.assertNotContains(response, reverse('admin:board_resource_add'))
        self.assertEqual(response.context['page_obj'].paginator.count, 3)

    def test_each_category_filters_the_feed(self):
        titles = {'topic': '选题卡片', 'showcase': '分享卡片', 'resource': '讲义卡片'}
        for kind, expected in titles.items():
            with self.subTest(kind=kind):
                response = self.client.get('/', {'kind': kind})
                self.assertContains(response, expected)
                for other in set(titles.values()) - {expected}:
                    self.assertNotContains(response, other)
                self.assertEqual(response.context['page_obj'].paginator.count, 1)

    def test_mixed_feed_order_pagination_and_week_filter(self):
        now = timezone.now()
        Post.objects.filter(pk=self.topic.pk).update(created_at=now - timedelta(days=15))
        Post.objects.filter(pk=self.share.pk).update(created_at=now - timedelta(days=16))
        Resource.objects.filter(pk=self.resource.pk).update(created_at=now - timedelta(days=14))
        for i in range(22):
            post = Post.objects.create(author=self.student, title=f'分页-{i:02}', body='内容', kind='topic')
            Post.objects.filter(pk=post.pk).update(created_at=now - timedelta(seconds=i))
        first = self.client.get('/').context['page_obj']
        second = self.client.get('/', {'page': 2}).context['page_obj']
        self.assertEqual(first.paginator.count, 25)
        self.assertEqual(len(first), 20)
        self.assertEqual(len(second), 5)
        def title(entry):
            return (entry.get('post') or entry.get('resource')).title
        self.assertEqual([title(e) for e in first] + [title(e) for e in second],
                         [f'分页-{i:02}' for i in range(22)] + ['讲义卡片', '选题卡片', '分享卡片'])
        recent = self.client.get('/', {'week': 'current'})
        self.assertNotContains(recent, '讲义卡片')
        self.assertNotContains(recent, '选题卡片')
        resource_recent = self.client.get('/', {'kind': 'resource', 'week': 'current'})
        self.assertEqual(resource_recent.context['page_obj'].paginator.count, 0)

    def test_resource_changes_are_reflected_without_duplicate_posts(self):
        self.resource.title = '更新后的讲义'
        self.resource.save()
        self.assertContains(self.client.get('/'), '更新后的讲义')
        self.resource.delete()
        self.assertNotContains(self.client.get('/'), '更新后的讲义')
        self.assertEqual(Post.objects.count(), 2)

    def test_pdf_download_and_staff_upload_links(self):
        pdf = Resource.objects.create(title='PDF讲义', file=SimpleUploadedFile('lecture.pdf', b'%PDF'))
        response = self.client.get('/', {'kind': 'resource'})
        self.assertContains(response, reverse('board:resource_download', args=[pdf.pk]))
        self.assertNotContains(response, reverse('board:resource_read', args=[pdf.pk]))
        self.student.is_staff = True
        self.student.save()
        self.assertContains(self.client.get('/', {'kind': 'resource'}), reverse('admin:board_resource_add'))

    def test_popular_and_pinned_order_and_invalid_filters(self):
        from .models import Like
        Like.objects.create(post=self.share, user=self.student)
        response = self.client.get('/', {'sort': 'popular'})
        self.assertEqual(response.context['page_obj'][0]['post'].pk, self.share.pk)
        self.topic.pinned = True
        self.topic.save()
        self.assertEqual(self.client.get('/').context['page_obj'][0]['post'].pk, self.topic.pk)
        invalid = self.client.get('/', {'kind': 'invalid', 'sort': 'invalid', 'week': 'invalid', 'page': 999})
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, '讲义卡片')
        self.client.logout()
        self.assertEqual(self.client.get('/').status_code, 302)
