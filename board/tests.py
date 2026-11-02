import csv
import io
import re
import tempfile
import zipfile
from PIL import Image, PngImagePlugin
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from .models import Comment, Like, LoginAttempt, Notification, Post, Resource


GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BoardTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user("20260001", password="pw", first_name="张三")
        self.other = User.objects.create_user("20260002", password="pw", first_name="李四")
        self.staff = User.objects.create_user("teacher", password="pw", is_staff=True, first_name="教师")
        self.post = Post.objects.create(author=self.student, title="T", body="B", kind="topic", anonymous=True)

    def test_content_requires_login_and_health_does_not(self):
        self.assertEqual(self.client.get(reverse("board:home")).status_code, 302)
        self.assertEqual(self.client.get("/healthz/").content, b"ok")

    def test_create_validates_safe_link_and_real_image(self):
        self.client.force_login(self.student)
        bad_link = self.client.post(reverse("board:post_create"), {"title": "x", "body": "b", "kind": "topic", "link": "javascript:alert(1)"})
        self.assertEqual(bad_link.status_code, 200)
        self.assertIn("link", bad_link.context["form"].errors)
        fake = SimpleUploadedFile("fake.png", b"not-image", content_type="image/png")
        bad_image = self.client.post(reverse("board:post_create"), {"title": "x", "body": "b", "kind": "topic", "image": fake})
        self.assertEqual(bad_image.status_code, 200)
        self.assertIn("image", bad_image.context["form"].errors)
        self.assertEqual(Post.objects.count(), 1)

    def test_form_feed_and_image_preservation(self):
        self.client.force_login(self.student)
        form_response = self.client.get(reverse("board:post_create"))
        self.assertContains(form_response, 'name="audio"')
        self.assertContains(form_response, 'accept="audio/mpeg,audio/mp4,audio/wav,audio/ogg"')

        stream = io.BytesIO()
        info = PngImagePlugin.PngInfo()
        info.add_text("Author", "保留")
        Image.new("RGB", (2, 2), "red").save(stream, "PNG", pnginfo=info)
        response = self.client.post(
            reverse("board:post_create"),
            {
                "title": "原样",
                "body": "正文",
                "kind": "showcase",
                "image": SimpleUploadedFile("我的图片.png", stream.getvalue(), content_type="image/png"),
            },
        )
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title="原样")
        self.assertTrue(post.image.name.endswith("/我的图片.png"))
        with Image.open(post.image.path) as image:
            self.assertEqual(image.info["Author"], "保留")

        media_post = Post.objects.create(
            author=self.student,
            title="带媒体的分享",
            body="正文",
            kind=Post.Kind.SHOWCASE,
            audio=SimpleUploadedFile("片段.mp3", b"ID3\x04\x00\x00\x00\x00\x00\x00"),
            video_link="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        feed = self.client.get(reverse("board:home"))
        self.assertContains(
            feed,
            f'<audio class="post-audio post-audio-compact" controls preload="metadata" src="{reverse("board:post_audio", args=[media_post.pk])}"',
        )
        self.assertContains(feed, f'href="{reverse("board:post_detail", args=[media_post.pk])}"')
        self.assertNotContains(feed, media_post.video_link)

    def test_create_accepts_audio_and_private_audio_requires_login(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("board:post_create"),
            {
                "title": "录音",
                "body": "正文",
                "kind": "showcase",
                "audio": SimpleUploadedFile("课堂.mp3", b"ID3\x04\x00\x00\x00\x00\x00\x00"),
            },
        )
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title="录音")
        self.assertTrue(post.audio.name.endswith("/课堂.mp3"))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("board:post_audio", args=[post.pk])).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("board:post_audio", args=[post.pk])).status_code, 200)

    def test_create_rejects_invalid_audio_and_media_urls(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("board:post_create"),
            {
                "title": "无效",
                "body": "正文",
                "kind": "showcase",
                "audio": SimpleUploadedFile("bad.exe", b"x"),
                "audio_link": "javascript:alert(1)",
                "video_link": "file:///x",
            },
        )
        self.assertIn("audio", response.context["form"].errors)
        self.assertIn("audio_link", response.context["form"].errors)
        self.assertIn("video_link", response.context["form"].errors)

    def test_like_is_unique_and_post_only(self):
        self.client.force_login(self.other)
        url = reverse("board:post_like", args=[self.post.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(Like.objects.filter(post=self.post, user=self.other).count(), 0)

    def test_student_comment_notifies_staff_and_reply_notifies_comment_author(self):
        self.staff.is_superuser = True
        self.staff.save(update_fields=["is_superuser"])
        self.client.force_login(self.other)
        self.client.post(reverse("board:comment_create", args=[self.post.pk]), {"body": "老师，请看这里"})
        comment = Comment.objects.get(body="老师，请看这里")
        self.assertTrue(Notification.objects.filter(recipient=self.staff, kind=Notification.Kind.NEW_COMMENT, comment=comment).exists())

        self.client.force_login(self.staff)
        self.client.post(reverse("board:comment_create", args=[self.post.pk]), {"body": "我看到了", "parent_id": comment.pk})
        self.assertTrue(Notification.objects.filter(recipient=self.other, kind=Notification.Kind.COMMENT_REPLY).exists())

    def test_post_like_notifies_author_and_notification_center_marks_read(self):
        self.client.force_login(self.other)
        self.client.post(reverse("board:post_like", args=[self.post.pk]))
        notification = Notification.objects.get(recipient=self.student, kind=Notification.Kind.POST_LIKE)
        self.assertIsNone(notification.read_at)

        self.client.force_login(self.student)
        response = self.client.get(reverse("board:notifications"))
        notification.refresh_from_db()
        self.assertContains(response, "有人赞同了你的帖子")
        self.assertIsNone(notification.read_at)
        self.client.post(reverse("board:notification_open", args=[notification.pk]))
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_owner_permissions_for_delete(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse("board:post_delete", args=[self.post.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())
        self.client.force_login(self.student)
        self.assertRedirects(self.client.post(reverse("board:post_delete", args=[self.post.pk])), reverse("board:home"))

    def test_anonymous_identity_absent_for_student_but_staff_can_see_name(self):
        self.client.force_login(self.other)
        student_html = self.client.get(reverse("board:post_detail", args=[self.post.pk])).content.decode()
        self.assertNotIn("张三", student_html)
        self.assertNotIn("20260001", student_html)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("board:post_detail", args=[self.post.pk])), "张三")

    def test_private_downloads_and_original_image_name(self):
        image = SimpleUploadedFile("student-number.png", GIF, content_type="image/gif")
        self.post.image = image
        self.post.save()
        self.assertTrue(self.post.image.name.endswith("/student-number.png"))
        self.assertEqual(self.client.get(reverse("board:post_image", args=[self.post.pk])).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("board:post_image", args=[self.post.pk])).status_code, 200)
        resource = Resource.objects.create(title="R", file=SimpleUploadedFile("notes.pdf", b"%PDF-1.4\n"))
        response = self.client.get(reverse("board:resource_download", args=[resource.pk]))
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="notes.pdf"')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_authenticated_dynamic_responses_are_not_cacheable(self):
        self.client.force_login(self.other)
        resource = Resource.objects.create(title="R", file=SimpleUploadedFile("notes.pdf", b"%PDF-1.4\n"))
        for url in [
            reverse("board:home"),
            reverse("board:post_detail", args=[self.post.pk]),
            reverse("board:resource_download", args=[resource.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0, must-revalidate")
            self.assertEqual(response["Pragma"], "no-cache")
            self.assertEqual(response["Expires"], "0")

    def test_login_response_is_not_cacheable_but_whitenoise_static_is(self):
        login_response = self.client.get(reverse("login"))
        self.assertEqual(login_response["Cache-Control"], "private, no-store, max-age=0, must-revalidate")
        with self.settings(DEBUG=False):
            static_response = self.client.get("/static/board/favicon.svg")
        self.assertEqual(static_response.status_code, 200)
        self.assertNotIn("private", static_response.get("Cache-Control", ""))
        self.assertNotIn("no-store", static_response.get("Cache-Control", ""))

    def test_comment_report_and_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.other)
        url = reverse("board:comment_create", args=[self.post.pk])
        self.assertEqual(csrf_client.post(url, {"body": "hi"}).status_code, 403)
        self.client.force_login(self.other)
        self.client.post(url, {"body": "hi", "anonymous": True})
        self.assertEqual(Comment.objects.filter(post=self.post).count(), 1)
        self.client.post(reverse("board:report_post", args=[self.post.pk]), {"reason": "spam"})
        self.assertEqual(self.post.reports.count(), 1)

    def test_student_cannot_enter_admin_and_logout_is_post_only(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))

    def test_login_throttles_after_five_failures(self):
        for _ in range(5):
            self.client.post(reverse("login"), {"username": self.student.username, "password": "wrong"})
        response = self.client.post(reverse("login"), {"username": self.student.username, "password": "pw"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "登录尝试过多")
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertEqual(LoginAttempt.objects.filter(username=self.student.username).count(), 5)

    def test_login_throttle_strips_username_and_covers_admin_login(self):
        for value in ["ｔｅａｃｈｅｒ", f"{self.staff.username} ", f" {self.staff.username} ", self.staff.username, self.staff.username]:
            self.client.post(reverse("login"), {"username": value, "password": "wrong"})
        response = self.client.post(reverse("login"), {"username": self.staff.username, "password": "pw"})
        self.assertContains(response, "登录尝试过多")
        LoginAttempt.objects.all().delete()
        for _ in range(5):
            self.client.post("/admin/login/", {"username": self.staff.username, "password": "wrong", "next": "/admin/"})
        response = self.client.post("/admin/login/", {"username": self.staff.username, "password": "pw", "next": "/admin/"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "登录尝试过多")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_login_throttle_trusts_real_ip_only_from_valid_loopback_proxy(self):
        login_url = reverse("login")
        for _ in range(5):
            self.client.post(
                login_url,
                {"username": self.student.username, "password": "wrong"},
                REMOTE_ADDR="127.0.0.1",
                HTTP_X_REAL_IP="203.0.113.10",
            )
        allowed_other_proxy_client = self.client.post(
            login_url,
            {"username": self.student.username, "password": "pw"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_REAL_IP="203.0.113.11",
        )
        self.assertRedirects(allowed_other_proxy_client, reverse("board:home"))
        self.client.logout()
        self.client.post(
            login_url,
            {"username": self.other.username, "password": "wrong"},
            REMOTE_ADDR="198.51.100.20",
            HTTP_X_REAL_IP="203.0.113.99",
        )
        self.assertTrue(LoginAttempt.objects.filter(username=self.other.username, ip_address="198.51.100.20").exists())
        self.client.logout()
        self.client.post(
            login_url,
            {"username": self.staff.username, "password": "wrong"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_REAL_IP="not-an-ip",
        )
        self.assertTrue(LoginAttempt.objects.filter(username=self.staff.username, ip_address="127.0.0.1").exists())

    def test_authenticated_login_redirects_to_safe_destination_or_home(self):
        self.client.force_login(self.student)
        self.assertRedirects(self.client.get(reverse("login")), reverse("board:home"))
        self.assertRedirects(
            self.client.get(reverse("login") + "?next=" + reverse("board:settings")),
            reverse("board:settings"),
        )
        self.assertRedirects(
            self.client.get(reverse("login") + "?next=https://evil.example/"),
            reverse("board:home"),
        )
        self.client.force_login(self.staff)
        self.assertRedirects(self.client.get("/admin/login/?next=/admin/"), "/admin/")

    def test_authenticated_nonstaff_admin_login_does_not_redirect_loop(self):
        self.client.force_login(self.student)
        response = self.client.get("/admin/login/?next=/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "没有这个页面的访问权限")

    def test_authenticated_nonstaff_failed_admin_reauthentication_is_throttled(self):
        self.client.force_login(self.student)
        for _ in range(5):
            self.client.post(
                "/admin/login/",
                {"username": self.staff.username, "password": "wrong", "next": "/admin/"},
            )
        self.assertEqual(LoginAttempt.objects.filter(username=self.staff.username).count(), 5)
        response = self.client.post(
            "/admin/login/",
            {"username": self.staff.username, "password": "pw", "next": "/admin/"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "登录尝试过多")

    def test_resource_extension_and_size_are_validated(self):
        resource = Resource(title="bad", file=SimpleUploadedFile("attack.html", b"<script>"))
        with self.assertRaises(ValidationError):
            resource.full_clean()

    def test_markdown_resource_reading_mode_is_safe_and_login_protected(self):
        md_text = "# 讲义标题\n\n<script>alert(1)</script>\n\n| 列一 | 列二 |\n|---|---|\n| 1 | 2 |\n\n[xss](javascript:alert(1))"
        resource = Resource.objects.create(title="讲义", file=SimpleUploadedFile("lesson.md", md_text.encode()))
        self.assertTrue(resource.is_markdown)
        read_url = reverse("board:resource_read", args=[resource.pk])
        self.assertEqual(self.client.get(read_url).status_code, 302)
        self.client.force_login(self.other)
        response = self.client.get(read_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("<h1>讲义标题</h1>", content)
        self.assertIn("<table>", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertNotIn("<script>alert(1)</script>", content)
        self.assertNotIn('href="javascript:', content)
        pdf = Resource.objects.create(title="PDF", file=SimpleUploadedFile("notes.pdf", b"%PDF-1.4\n"))
        self.assertFalse(pdf.is_markdown)
        self.assertRedirects(self.client.get(reverse("board:resource_read", args=[pdf.pk])), reverse("board:resource_download", args=[pdf.pk]))

    def test_create_preselects_kind_and_preserves_anonymous_image_metadata(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("board:post_create") + "?kind=showcase")
        self.assertEqual(response.context["form"].initial["kind"], "showcase")
        stream = io.BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Author", "student-identity")
        Image.new("RGB", (2, 2), "red").save(stream, "PNG", pnginfo=metadata)
        upload = SimpleUploadedFile("identity.png", stream.getvalue(), content_type="image/png")
        response = self.client.post(reverse("board:post_create"), {"title": "image", "body": "body", "kind": "showcase", "anonymous": True, "image": upload})
        post = Post.objects.get(title="image")
        self.assertTrue(post.image.name.endswith("/identity.png"))
        with Image.open(post.image.path) as saved:
            self.assertEqual(saved.info["Author"], "student-identity")

    def test_admin_post_upload_preserves_image_metadata_and_keeps_admin_fields(self):
        self.staff.is_superuser = True
        self.staff.save(update_fields=["is_superuser"])
        self.client.force_login(self.staff)
        stream = io.BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Author", "SYNTHETIC-STUDENT-IDENTITY")
        Image.new("RGB", (2, 2), "red").save(stream, "PNG", pnginfo=metadata)
        response = self.client.post(
            reverse("admin:board_post_add"),
            {
                "author": self.student.pk,
                "title": "admin image",
                "body": "body",
                "kind": Post.Kind.SHOWCASE,
                "anonymous": "on",
                "status": Post.Status.ANSWERED,
                "pinned": "on",
                "image": SimpleUploadedFile("identity.png", stream.getvalue(), content_type="image/png"),
                "projects-TOTAL_FORMS": "0",
                "projects-INITIAL_FORMS": "0",
                "_save": "保存",
            },
        )
        self.assertEqual(response.status_code, 302, response.context and response.context["adminform"].form.errors)
        post = Post.objects.get(title="admin image")
        self.assertEqual(post.author, self.student)
        self.assertEqual(post.status, Post.Status.ANSWERED)
        self.assertTrue(post.pinned)
        with Image.open(post.image.path) as saved:
            self.assertEqual(saved.info["Author"], "SYNTHETIC-STUDENT-IDENTITY")
        replacement = io.BytesIO()
        replacement_metadata = PngImagePlugin.PngInfo()
        replacement_metadata.add_text("Author", "REPLACEMENT-STUDENT-IDENTITY")
        Image.new("RGB", (2, 2), "blue").save(replacement, "PNG", pnginfo=replacement_metadata)
        response = self.client.post(
            reverse("admin:board_post_change", args=[post.pk]),
            {
                "author": self.student.pk,
                "title": post.title,
                "body": post.body,
                "kind": post.kind,
                "anonymous": "on",
                "status": post.status,
                "pinned": "on",
                "image": SimpleUploadedFile("replacement.png", replacement.getvalue(), content_type="image/png"),
                "projects-TOTAL_FORMS": "0",
                "projects-INITIAL_FORMS": "0",
                "_save": "保存",
            },
        )
        self.assertEqual(response.status_code, 302, response.context and response.context["adminform"].form.errors)
        post.refresh_from_db()
        with Image.open(post.image.path) as saved:
            self.assertEqual(saved.info["Author"], "REPLACEMENT-STUDENT-IDENTITY")

    def test_replacing_resource_updates_download_filename(self):
        resource = Resource.objects.create(title="R", file=SimpleUploadedFile("slides.pptx", b"first"))
        self.assertEqual(resource.original_filename, "slides.pptx")
        resource.file = SimpleUploadedFile("notes.pdf", b"%PDF-1.4\n")
        resource.save()
        resource.refresh_from_db()
        self.assertEqual(resource.original_filename, "notes.pdf")

    def test_static_asset_is_discoverable_and_detail_has_like_count(self):
        from django.contrib.staticfiles import finders
        self.assertTrue(finders.find("board/app.css"))
        Like.objects.create(post=self.post, user=self.other)
        self.client.force_login(self.student)
        response = self.client.get(reverse("board:post_detail", args=[self.post.pk]))
        self.assertEqual(response.context["post"].like_count, 1)

    def test_video_embed_url_whitelists_known_video_ids(self):
        from .media import video_embed_url

        self.assertEqual(
            video_embed_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        )
        self.assertEqual(
            video_embed_url("https://www.bilibili.com/video/BV1xx411c7mD"),
            "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD",
        )
        self.assertIsNone(video_embed_url("https://evil.example/?src=youtube.com"))

    def test_unknown_video_is_external_link_not_iframe(self):
        self.post.video_link = "https://video.example/one"
        self.post.save()
        self.client.force_login(self.other)

        response = self.client.get(reverse("board:post_detail", args=[self.post.pk]))

        self.assertNotContains(response, "<iframe")
        self.assertContains(response, "打开视频链接")


class ImportStudentsTests(TestCase):
    def test_csv_import_is_idempotent_and_keeps_changed_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "students.csv"
            path.write_text("student_id,name\n20260001,张三\n", encoding="utf-8-sig")
            call_command("import_students", str(path))
            user = User.objects.get(username="20260001")
            user.set_password("changed")
            user.save()
            call_command("import_students", str(path))
            user.refresh_from_db()
            self.assertTrue(user.check_password("changed"))

    def test_xlsx_resets_bad_dimension_and_finds_chinese_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "students.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.cell(5, 2, "学号")
            sheet.cell(5, 3, "姓名")
            sheet.cell(6, 2, "D1234567")
            sheet.cell(6, 3, "王五")
            book.save(path)
            with zipfile.ZipFile(path) as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            entries["xl/worksheets/sheet1.xml"] = re.sub(
                br'<dimension ref="[^"]+"/>', b'<dimension ref="A1"/>', entries["xl/worksheets/sheet1.xml"]
            )
            with zipfile.ZipFile(path, "w") as archive:
                for name, data in entries.items():
                    archive.writestr(name, data)
            call_command("import_students", str(path))
            self.assertEqual(User.objects.get(username="D1234567").first_name, "王五")

    def test_conflicting_duplicate_rolls_back_and_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "students.csv"
            path.write_text("student_id,name\n20260001,张三\n20260001,李四\n", encoding="utf-8")
            with self.assertRaises(Exception):
                call_command("import_students", str(path))
            self.assertFalse(User.objects.filter(username="20260001").exists())
            path.write_text("student_id,name\n20260002,李四\n", encoding="utf-8")
            call_command("import_students", str(path), dry_run=True)
            self.assertFalse(User.objects.filter(username="20260002").exists())
