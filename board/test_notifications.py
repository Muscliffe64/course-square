from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from .models import Comment, Notification, Post


class NotificationSafetyTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user("owner", first_name="接收人")
        self.other = User.objects.create_user("secret-id", first_name="保密姓名")
        self.teacher = User.objects.create_user("teacher", is_staff=True)
        self.post = Post.objects.create(author=self.student, title="讨论", body="内容", kind="topic")

    def test_anonymous_reply_and_owner_only_read(self):
        parent = Comment.objects.create(author=self.student, post=self.post, body="问题")
        self.client.force_login(self.other)
        self.client.post(reverse("board:comment_create", args=[self.post.pk]),
                         {"body": "回答", "anonymous": "on", "parent_id": parent.pk})
        item = Notification.objects.get(recipient=self.student)
        self.assertEqual(self.client.post(reverse("board:notification_open", args=[item.pk])).status_code, 404)
        self.client.force_login(self.student)
        response = self.client.get(reverse("board:notifications"))
        self.assertContains(response, "匿名同学")
        self.assertNotContains(response, "保密姓名")
        self.assertNotContains(response, "secret-id")
        item.refresh_from_db()
        self.assertIsNone(item.read_at)
        self.assertEqual(self.client.get(reverse("board:notification_open", args=[item.pk])).status_code, 405)
        self.client.post(reverse("board:notifications_read"))
        self.assertFalse(Notification.objects.filter(recipient=self.student, read_at=None).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.teacher, read_at=None).exists())

    def test_staff_reply_notification_is_not_duplicated(self):
        parent = Comment.objects.create(author=self.teacher, post=self.post, body="老师问题")
        self.client.force_login(self.other)
        self.client.post(reverse("board:comment_create", args=[self.post.pk]), {"body": "回答", "parent_id": parent.pk})
        self.assertEqual(Notification.objects.filter(recipient=self.teacher).count(), 1)

    def test_repeated_like_does_not_spam(self):
        self.client.force_login(self.other)
        for _ in range(3):
            self.client.post(reverse("board:post_like", args=[self.post.pk]))
        self.assertEqual(Notification.objects.filter(recipient=self.student).count(), 1)

    def test_reply_cannot_target_another_post(self):
        other_post = Post.objects.create(author=self.other, title="另一个", body="内容", kind="topic")
        parent = Comment.objects.create(author=self.other, post=other_post, body="原留言")
        self.client.force_login(self.student)
        response = self.client.post(reverse("board:comment_create", args=[self.post.pk]), {"body": "越界", "parent_id": parent.pk})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.filter(body="越界").exists())
