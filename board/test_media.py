import io
import re
import tempfile
from email.message import Message
from pathlib import Path

from PIL import Image
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .forms import PostAdminForm, PostForm
from .media import video_embed_url
from .models import MAX_AUDIO_BYTES, MAX_IMAGE_BYTES, Post, validate_audio


class PostMediaTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        cls.addClassCleanup(settings.disable)

    def setUp(self):
        self.user = User.objects.create_user("media-student")
        self.client.force_login(self.user)

    def make_post(self, **kwargs):
        return Post.objects.create(author=self.user, title="媒体", body="正文", kind="showcase", **kwargs)

    def image_upload(self, name="图片.png"):
        data = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(data, "PNG")
        return SimpleUploadedFile(name, data.getvalue(), "image/png")

    def test_original_names_survive_storage_sanitization_and_long_names(self):
        names = ['我的 #课堂 & "分享".png', "long_" + "a" * 175 + ".png"]
        for image_name in names:
            audio_name = image_name[:-4] + ".mp3"
            with self.subTest(name=image_name):
                post = self.make_post(image=self.image_upload(image_name), audio=SimpleUploadedFile(audio_name, b"ID3original"))
                post.refresh_from_db()
                self.assertEqual(getattr(post, "image_original_filename", None), image_name)
                self.assertEqual(getattr(post, "audio_original_filename", None), audio_name)
                for field, name in (("image", image_name), ("audio", audio_name)):
                    response = self.client.get(reverse(f"board:post_{field}", args=[post.pk]))
                    self.addCleanup(response.close)
                    header = Message()
                    header["Content-Disposition"] = response["Content-Disposition"]
                    self.assertEqual(header.get_content_disposition(), "inline")
                    self.assertEqual(header.get_filename(), name)
                detail = self.client.get(reverse("board:post_detail", args=[post.pk]))
                from django.utils.html import escape
                self.assertContains(detail, escape(image_name))
                self.assertContains(detail, escape(audio_name))

    def test_original_names_change_only_when_upload_is_replaced(self):
        post = self.make_post(image=self.image_upload("original #.png"), audio=SimpleUploadedFile("original #.mp3", b"first"))
        post.title = "修改标题"
        post.save(update_fields=["title"])
        post.refresh_from_db()
        self.assertEqual(getattr(post, "image_original_filename", None), "original #.png")
        self.assertEqual(getattr(post, "audio_original_filename", None), "original #.mp3")
        post.image = self.image_upload("replacement &.png")
        post.audio = SimpleUploadedFile("replacement &.mp3", b"second")
        post.save(update_fields=["image", "audio"])
        post.refresh_from_db()
        self.assertEqual(post.image_original_filename, "replacement &.png")
        self.assertEqual(post.audio_original_filename, "replacement &.mp3")

    def test_long_original_names_are_accepted_by_publishing_form(self):
        image_name = "long_" + "a" * 175 + ".png"
        audio_name = "long_" + "b" * 175 + ".mp3"
        response = self.client.post(reverse("board:post_create"), {
            "title": "长文件名", "body": "正文", "kind": "showcase",
            "image": self.image_upload(image_name),
            "audio": SimpleUploadedFile(audio_name, b"ID3audio"),
        })
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title="长文件名")
        self.assertEqual(post.image_original_filename, image_name)
        self.assertEqual(post.audio_original_filename, audio_name)

    def test_old_records_use_storage_basename_in_headers(self):
        post = self.make_post(image=self.image_upload("legacy.png"), audio=SimpleUploadedFile("legacy.mp3", b"old"))
        for field in ("image", "audio"):
            original_field = f"{field}_original_filename"
            if hasattr(post, original_field):
                Post.objects.filter(pk=post.pk).update(**{original_field: ""})
            response = self.client.get(reverse(f"board:post_{field}", args=[post.pk]))
            self.addCleanup(response.close)
            self.assertEqual(response["Content-Disposition"], f'inline; filename="{Path(getattr(post, field).name).name}"')

    def test_concrete_media_content_types(self):
        for extension, expected in {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "ogg": "audio/ogg"}.items():
            with self.subTest(extension=extension):
                post = self.make_post(audio=SimpleUploadedFile("录音." + extension.upper(), b"audio"))
                response = self.client.get(reverse("board:post_audio", args=[post.pk]))
                self.addCleanup(response.close)
                self.assertEqual(response["Content-Type"], expected)
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        for extension, expected in {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.items():
            post = self.make_post(image=self.image_upload("图." + extension))
            response = self.client.get(reverse("board:post_image", args=[post.pk]))
            self.addCleanup(response.close)
            self.assertEqual(response["Content-Type"], expected)

    def test_missing_media_returns_404(self):
        post = self.make_post(image="post-images/missing.png", audio="post-audio/missing.mp3")
        self.client.raise_request_exception = False
        for field in ("image", "audio"):
            with self.subTest(field=field):
                self.assertEqual(self.client.get(reverse(f"board:post_{field}", args=[post.pk])).status_code, 404)

    def test_unknown_legacy_extensions_are_served_as_inert_bytes(self):
        post = self.make_post(image=SimpleUploadedFile("old.html", b"<html>"), audio=SimpleUploadedFile("old.svg", b"<svg>"))
        for field in ("image", "audio"):
            response = self.client.get(reverse(f"board:post_{field}", args=[post.pk]))
            self.addCleanup(response.close)
            self.assertEqual(response["Content-Type"], "application/octet-stream")
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_admin_form_preserves_long_original_upload_names(self):
        name = "recording_" + "a" * 230 + ".mp3"
        form = PostAdminForm({
            "author": self.user.pk, "title": "后台上传", "body": "正文", "kind": "showcase", "status": "open",
        }, {"audio": SimpleUploadedFile(name, b"audio")})
        self.assertTrue(form.is_valid(), form.errors)
        post = form.save()
        post.refresh_from_db()
        self.assertEqual(post.audio_original_filename, name)

    def test_image_audio_and_links_can_be_published_together(self):
        response = self.client.post(reverse("board:post_create"), {
            "title": "组合", "body": "正文", "kind": "showcase",
            "image": self.image_upload("图片 #.png"),
            "audio": SimpleUploadedFile("音频 #.mp3", b"ID3original-metadata"),
            "audio_link": "https://example.com/recording.mp3",
            "video_link": "https://youtu.be/dQw4w9WgXcQ",
        })
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title="组合")
        self.assertTrue(post.image and post.audio)
        with post.audio.open("rb") as audio:
            self.assertEqual(audio.read(), b"ID3original-metadata")
        detail = self.client.get(response.url)
        self.assertContains(detail, "<audio", count=2)
        self.assertContains(detail, "<iframe")
        self.assertContains(detail, 'href="https://youtu.be/dQw4w9WgXcQ"')
        self.assertContains(detail, "打开视频链接")

    def test_publish_form_hides_admin_identity_note_but_exposes_media_fields(self):
        response = self.client.get(reverse("board:post_create"))
        self.assertContains(response, 'name="audio"')
        self.assertContains(response, 'name="audio_link"')
        self.assertContains(response, 'name="video_link"')
        self.assertNotContains(response, "管理员可以查看真实姓名")

    def test_embedded_video_always_has_external_fallback(self):
        post = self.make_post(video_link="https://www.bilibili.com/video/BV1xx411c7mD")
        response = self.client.get(reverse("board:post_detail", args=[post.pk]))
        self.assertContains(response, "<iframe")
        self.assertContains(response, f'href="{post.video_link}" target="_blank" rel="noopener noreferrer"')
        self.assertContains(response, "打开视频链接")


class MediaValidationTests(SimpleTestCase):
    def test_audio_extensions_and_size_boundaries(self):
        for extension in ("mp3", "M4A", "wav", "OGG"):
            upload = SimpleUploadedFile("录音." + extension, b"small fixture")
            upload.size = MAX_AUDIO_BYTES
            validate_audio(upload)
            upload.size += 1
            with self.assertRaisesMessage(ValidationError, "音频不能超过 25 MB"):
                validate_audio(upload)
        for extension in ("mp4", "exe", "svg", "mp3.exe", ""):
            with self.assertRaises(ValidationError):
                validate_audio(SimpleUploadedFile("recording." + extension, b"small"))

    def test_form_rejects_oversized_audio(self):
        upload = SimpleUploadedFile("录音.mp3", b"small fixture")
        upload.size = MAX_AUDIO_BYTES + 1
        form = PostForm({"title": "组合", "body": "正文", "kind": "showcase"}, {"audio": upload})
        self.assertFalse(form.is_valid())
        self.assertIn("音频不能超过 25 MB", form.errors["audio"][0])

    def test_youtube_url_variants(self):
        for url in (
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?si=abc",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        ):
            with self.subTest(url=url):
                self.assertEqual(video_embed_url(url), "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")

    def test_tencent_practical_urls(self):
        for url in (
            "https://v.qq.com/x/page/a1234567890.html",
            "https://v.qq.com/x/cover/cover123/a1234567890.html?ptag=share",
            "https://v.qq.com/txp/iframe/player.html?vid=a1234567890",
        ):
            with self.subTest(url=url):
                self.assertEqual(video_embed_url(url), "https://v.qq.com/txp/iframe/player.html?vid=a1234567890")

    def test_hostile_and_unresolved_urls_are_not_embedded(self):
        for url in (
            "javascript:alert(1)", "file:///etc/passwd", "//youtu.be/dQw4w9WgXcQ",
            "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ",
            "https://youtube.com@evil.test/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=%22%3E%3Cscript%3E",
            "https://evil.test/x/page/a1234567890.html",
            "https://v.qq.com/x/page/%3Cscript%3E.html",
            "https://v.qq.com/x/page/a1234567890.html/extra",
            "https://b23.tv/abcdefg", "https://[invalid/",
        ):
            with self.subTest(url=url):
                self.assertIsNone(video_embed_url(url))

    def test_nginx_accepts_combined_maximum_uploads(self):
        config = (Path(__file__).resolve().parents[1] / "deploy/nginx.conf").read_text()
        limit = re.search(r"client_max_body_size\s+(\d+)m;", config)
        self.assertIsNotNone(limit)
        required = max(8 * MAX_IMAGE_BYTES, MAX_AUDIO_BYTES + MAX_IMAGE_BYTES)
        self.assertGreaterEqual(int(limit.group(1)) * 1024 * 1024, required + 1024 * 1024)
