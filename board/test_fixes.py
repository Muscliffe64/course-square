"""Regression tests for the 2026-09-21 audit fixes."""
import importlib
import io
import tempfile
from types import SimpleNamespace

from PIL import Image
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Comment, LoginAttempt, Notification, Post, PostImage, VisitLog

MEDIA = tempfile.mkdtemp()


def photo(name="photo.jpg", size=(3000, 2000), orientation=None):
    """A JPEG like a phone would produce: large, with EXIF (GPS + orientation)."""
    image = Image.new("RGB", size, "red")
    image.paste((0, 0, 255), (0, 0, size[0] // 2, size[1]))  # left half blue, to detect rotation
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"                 # Make
    exif[0x8825] = {1: "N", 2: (34.0, 15.0, 0.0)}  # GPSInfo: Xi'an-ish latitude
    if orientation:
        exif[0x0112] = orientation
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif, quality=90)
    return SimpleUploadedFile(name, buffer.getvalue(), "image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA)
class AnonymousNotificationTests(TestCase):
    def setUp(self):
        self.replier = User.objects.create_user("20260001", password="pw", first_name="张三")
        self.author = User.objects.create_user("20260002", password="pw", first_name="李四")
        self.staff = User.objects.create_user("teacher", password="pw", first_name="教师", is_staff=True)
        self.post = Post.objects.create(author=self.author, title="问题", body="正文", kind="topic")
        self.parent = Comment.objects.create(post=self.post, author=self.author, body="原留言")

    def anonymous_reply(self):
        self.client.force_login(self.replier)
        self.client.post(reverse("board:comment_create", args=[self.post.pk]),
                         {"body": "匿名回复", "anonymous": "on", "parent_id": self.parent.pk})
        return Comment.objects.get(body="匿名回复")

    def test_deleting_anonymous_reply_does_not_reveal_name(self):
        reply = self.anonymous_reply()
        self.client.post(reverse("board:comment_delete", args=[reply.pk]))
        self.assertFalse(Comment.objects.filter(pk=reply.pk).exists())
        self.client.force_login(self.author)
        page = self.client.get(reverse("board:notifications")).content.decode()
        self.assertIn("匿名同学", page)
        self.assertNotIn("张三", page)

    def test_staff_still_sees_identity_of_anonymous_commenter(self):
        reply = self.anonymous_reply()
        self.client.post(reverse("board:comment_delete", args=[reply.pk]))
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("board:notifications")), "张三")

    def test_named_reply_still_shows_name(self):
        self.client.force_login(self.replier)
        self.client.post(reverse("board:comment_create", args=[self.post.pk]),
                         {"body": "实名回复", "parent_id": self.parent.pk})
        self.client.force_login(self.author)
        self.assertContains(self.client.get(reverse("board:notifications")), "张三")

    def test_migration_backfill_hides_unknown_and_copies_known(self):
        anonymous = Comment.objects.create(post=self.post, author=self.replier, body="a", anonymous=True, parent=self.parent)
        named = Comment.objects.create(post=self.post, author=self.replier, body="b", parent=self.parent)
        known_anon = Notification.objects.create(recipient=self.author, actor=self.replier, kind="comment_reply", post=self.post, comment=anonymous)
        known_named = Notification.objects.create(recipient=self.author, actor=self.replier, kind="comment_reply", post=self.post, comment=named)
        orphan = Notification.objects.create(recipient=self.author, actor=self.replier, kind="comment_reply", post=self.post, comment=None)
        like = Notification.objects.create(recipient=self.author, actor=self.replier, kind="post_like", post=self.post)
        migration = importlib.import_module("board.migrations.0009_notification_actor_anonymous_postimage_thumbnail")
        migration.backfill_actor_anonymous(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
        values = dict(Notification.objects.values_list("pk", "actor_anonymous"))
        self.assertTrue(values[known_anon.pk])
        self.assertFalse(values[known_named.pk])
        self.assertTrue(values[orphan.pk])
        self.assertFalse(values[like.pk])


@override_settings(MEDIA_ROOT=MEDIA)
class ThumbnailAndCacheTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("20260001", password="pw", first_name="张三")
        self.client.force_login(self.user)

    def publish(self, upload):
        self.client.post(reverse("board:post_create"), {"kind": "showcase", "title": "作品", "body": "正文", "images": upload})
        post = Post.objects.get(title="作品")
        return post, post.gallery_images.get()

    def test_upload_creates_small_thumbnail_without_exif_and_keeps_original(self):
        upload = photo()
        original_bytes = upload.read(); upload.seek(0)
        post, image = self.publish(upload)
        self.assertTrue(image.thumbnail)
        with image.image.open("rb") as stored:
            self.assertEqual(stored.read(), original_bytes)  # original untouched, metadata included
        with Image.open(image.thumbnail.path) as thumb:
            self.assertLessEqual(max(thumb.size), 1200)
            self.assertFalse(thumb.getexif())
            self.assertNotIn("exif", thumb.info)
        self.assertLess(image.thumbnail.size, len(original_bytes))

    def test_thumbnail_follows_exif_orientation(self):
        _, image = self.publish(photo(size=(400, 200), orientation=6))  # "rotate 90° CW to display"
        with Image.open(image.thumbnail.path) as thumb:
            self.assertEqual(thumb.size, (200, 400))

    def test_pages_use_thumbnail_and_link_original(self):
        post, image = self.publish(photo())
        thumb_url = reverse("board:post_gallery_thumb", args=[post.pk, image.pk])
        original_url = reverse("board:post_gallery_image", args=[post.pk, image.pk])
        home = self.client.get(reverse("board:home")).content.decode()
        self.assertIn(thumb_url, home)
        self.assertNotIn(reverse("board:post_image", args=[post.pk]), home)
        detail = self.client.get(reverse("board:post_detail", args=[post.pk])).content.decode()
        self.assertIn(thumb_url, detail)
        self.assertIn(f'href="{original_url}"', detail)

    def test_media_is_privately_cacheable_but_pages_are_not(self):
        post, image = self.publish(photo())
        for name in ("board:post_gallery_thumb", "board:post_gallery_image"):
            response = self.client.get(reverse(name, args=[post.pk, image.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "private, max-age=86400")
            self.assertNotIn("Pragma", response)
        self.assertEqual(self.client.get(reverse("board:post_gallery_thumb", args=[post.pk, image.pk]))["Content-Type"], "image/webp")
        page = self.client.get(reverse("board:post_detail", args=[post.pk]))
        self.assertEqual(page["Cache-Control"], "private, no-store, max-age=0, must-revalidate")

    def test_media_still_requires_login(self):
        post, image = self.publish(photo())
        self.client.logout()
        self.assertEqual(self.client.get(reverse("board:post_gallery_thumb", args=[post.pk, image.pk])).status_code, 302)

    def test_missing_thumbnail_falls_back_and_command_backfills(self):
        post, image = self.publish(photo())
        PostImage.objects.filter(pk=image.pk).update(thumbnail="")
        response = self.client.get(reverse("board:post_gallery_thumb", args=[post.pk, image.pk]))
        self.assertEqual(response["Content-Type"], "image/jpeg")  # the original
        out = io.StringIO()
        call_command("generate_thumbnails", stdout=out)
        self.assertIn("created=1", out.getvalue())
        image.refresh_from_db()
        self.assertTrue(image.thumbnail)
        call_command("generate_thumbnails", stdout=out)
        self.assertIn("created=0", out.getvalue())

    def test_broken_image_file_does_not_block_publishing(self):
        post, image = self.publish(photo())
        PostImage.objects.filter(pk=image.pk).update(thumbnail="")
        with self.assertLogs("board.thumbnails", "ERROR"):
            broken = PostImage.objects.create(post=post, image="post-images/missing/none.png")
        self.assertFalse(broken.thumbnail)


@override_settings(MEDIA_ROOT=MEDIA)
class VisitLogTests(TestCase):
    def test_media_and_health_checks_are_not_logged(self):
        user = User.objects.create_user("20260001", password="pw", first_name="张三")
        self.client.force_login(user)
        self.client.post(reverse("board:post_create"), {"kind": "showcase", "title": "作品", "body": "正文", "images": photo()})
        post = Post.objects.get(title="作品"); image = post.gallery_images.get()
        VisitLog.objects.all().delete()
        self.client.get(reverse("board:post_gallery_thumb", args=[post.pk, image.pk]))
        self.client.get(reverse("board:post_gallery_image", args=[post.pk, image.pk]))
        self.client.get(reverse("board:post_image", args=[post.pk]))
        self.client.get("/healthz/")
        self.assertEqual(VisitLog.objects.count(), 0)
        self.client.get(reverse("board:post_detail", args=[post.pk]))
        self.assertEqual(list(VisitLog.objects.values_list("path", flat=True)), [reverse("board:post_detail", args=[post.pk])])


class LoginTests(TestCase):
    def setUp(self):
        self.default_user = User.objects.create_user("20260001", password="20260001", first_name="张三")
        self.changed_user = User.objects.create_user("20260002", password="a-real-password", first_name="李四")

    def test_ip_wide_failure_cap(self):
        for index in range(50):
            LoginAttempt.objects.create(username=f"x{index}", ip_address="127.0.0.1")
        response = self.client.post(reverse("login"), {"username": "20260002", "password": "a-real-password"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "登录尝试过多")

    def test_below_ip_cap_still_logs_in(self):
        for index in range(20):
            LoginAttempt.objects.create(username=f"x{index}", ip_address="127.0.0.1")
        response = self.client.post(reverse("login"), {"username": "20260002", "password": "a-real-password"})
        self.assertEqual(response.status_code, 302)

    def test_default_password_banner_until_changed(self):
        self.client.post(reverse("login"), {"username": "20260001", "password": "20260001"})
        self.assertContains(self.client.get(reverse("board:home")), "default-password-banner")
        self.client.post(reverse("password_change"), {
            "old_password": "20260001", "new_password1": "new-secret-9", "new_password2": "new-secret-9",
        })
        self.assertNotContains(self.client.get(reverse("board:home")), "default-password-banner")

    def test_no_banner_for_changed_password(self):
        self.client.post(reverse("login"), {"username": "20260002", "password": "a-real-password"})
        self.assertNotContains(self.client.get(reverse("board:home")), "default-password-banner")


class DatabaseSettingsTests(TestCase):
    def test_sqlite_uses_wal(self):
        options = settings.DATABASES["default"]["OPTIONS"]
        self.assertIn("journal_mode=WAL", options["init_command"])
        self.assertEqual(options["transaction_mode"], "IMMEDIATE")
