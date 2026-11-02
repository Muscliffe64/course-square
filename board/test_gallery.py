import io
import tempfile
from pathlib import Path

from PIL import Image
from django.contrib.auth.models import User
from django.contrib import admin
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Post, PostImage


class PostGalleryModelTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        cls.addClassCleanup(settings.disable)

    def setUp(self):
        self.user = User.objects.create_user("gallery-student")

    @staticmethod
    def image_upload(name="图片.png"):
        data = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(data, "PNG")
        return SimpleUploadedFile(name, data.getvalue(), "image/png")

    def test_selected_gallery_image_is_the_cover(self):
        post = Post.objects.create(author=self.user, title="多图", body="正文", kind="showcase")
        PostImage.objects.create(post=post, image=self.image_upload("第一张.png"))
        cover = PostImage.objects.create(post=post, image=self.image_upload("封面.png"), is_cover=True)

        post.refresh_from_db()

        self.assertEqual(post.cover_image.pk, cover.pk)
        self.assertEqual(post.cover_image_file.name, cover.image.name)
        self.assertEqual(post.cover_image_filename, "封面.png")

    def test_legacy_post_image_is_used_when_gallery_is_empty(self):
        post = Post.objects.create(
            author=self.user,
            title="旧图",
            body="正文",
            kind="showcase",
            image=self.image_upload("旧图片.png"),
        )

        self.assertIsNone(post.cover_image)
        self.assertEqual(post.cover_image_file.name, post.image.name)
        self.assertEqual(post.cover_image_filename, "旧图片.png")


class PostGalleryPublishTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        cls.addClassCleanup(settings.disable)

    def setUp(self):
        self.user = User.objects.create_user("publish-student")
        self.client.force_login(self.user)

    @staticmethod
    def image_upload(name="图片.png"):
        data = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(data, "PNG")
        return SimpleUploadedFile(name, data.getvalue(), "image/png")

    def publish_data(self, title="三张图", images=None, **extra):
        return {
            "title": title,
            "body": "正文",
            "kind": "showcase",
            "images": images or [self.image_upload("一.png"), self.image_upload("二.png")],
            **extra,
        }

    def test_publish_multiple_images_uses_selected_new_cover(self):
        response = self.client.post(
            reverse("board:post_create"),
            self.publish_data(cover_choice="new:1"),
        )

        post = Post.objects.get(title="三张图")

        self.assertRedirects(response, reverse("board:post_detail", args=[post.pk]))
        self.assertEqual(post.gallery_images.count(), 2)
        self.assertEqual(post.cover_image.original_filename, "二.png")

    def test_publish_rejects_more_than_eight_images(self):
        response = self.client.post(
            reverse("board:post_create"),
            self.publish_data(
                title="太多图",
                images=[self.image_upload(f"{index}.png") for index in range(9)],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("images", response.context["form"].errors)

    def test_publish_defaults_to_first_image_as_cover(self):
        response = self.client.post(reverse("board:post_create"), self.publish_data(title="两张图"))

        post = Post.objects.get(title="两张图")

        self.assertRedirects(response, reverse("board:post_detail", args=[post.pk]))
        self.assertEqual(post.cover_image.original_filename, "一.png")


class PostEditTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        cls.addClassCleanup(settings.disable)

    def setUp(self):
        self.user = User.objects.create_user("post-author")
        self.other_user = User.objects.create_user("other-student")
        self.staff = User.objects.create_user("course-staff", is_staff=True)
        self.client.force_login(self.user)

    @staticmethod
    def image_upload(name="图片.png"):
        data = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(data, "PNG")
        return SimpleUploadedFile(name, data.getvalue(), "image/png")

    def create_gallery_post(self, with_audio=False):
        post = Post.objects.create(
            author=self.user,
            title="可编辑内容",
            body="旧正文",
            kind="showcase",
            audio=SimpleUploadedFile("原音频.mp3", b"ID3old") if with_audio else None,
        )
        cover = PostImage.objects.create(post=post, image=self.image_upload("封面.png"), is_cover=True)
        other = PostImage.objects.create(post=post, image=self.image_upload("另一张.png"))
        return post, cover, other

    def test_author_can_edit_title_body_audio_and_cover(self):
        post, old_cover, other = self.create_gallery_post()

        response = self.client.post(reverse("board:post_edit", args=[post.pk]), {
            "title": "更新标题",
            "body": "更新正文",
            "kind": "showcase",
            "cover_choice": f"existing:{other.pk}",
            "audio": SimpleUploadedFile("新版.mp3", b"ID3new"),
        })

        post.refresh_from_db()

        self.assertRedirects(response, reverse("board:post_detail", args=[post.pk]))
        self.assertEqual(post.title, "更新标题")
        self.assertEqual(post.body, "更新正文")
        self.assertEqual(post.cover_image.pk, other.pk)
        self.assertEqual(post.audio_original_filename, "新版.mp3")
        self.assertFalse(PostImage.objects.get(pk=old_cover.pk).is_cover)

    def test_non_author_cannot_edit_post(self):
        post, _, _ = self.create_gallery_post()
        self.client.force_login(self.other_user)

        self.assertEqual(self.client.get(reverse("board:post_edit", args=[post.pk])).status_code, 403)

    def test_edit_without_new_files_keeps_existing_gallery_and_audio(self):
        post, cover, _ = self.create_gallery_post(with_audio=True)

        self.client.post(reverse("board:post_edit", args=[post.pk]), {
            "title": "只改文字",
            "body": "新正文",
            "kind": "showcase",
            "cover_choice": f"existing:{cover.pk}",
        })
        post.refresh_from_db()

        self.assertEqual(post.gallery_images.count(), 2)
        self.assertEqual(post.cover_image.pk, cover.pk)
        self.assertEqual(post.audio_original_filename, "原音频.mp3")

    def test_staff_can_edit_another_users_post(self):
        post, _, _ = self.create_gallery_post()
        self.client.force_login(self.staff)

        response = self.client.post(reverse("board:post_edit", args=[post.pk]), {
            "title": "管理员更新",
            "body": "正文",
            "kind": "showcase",
        })
        post.refresh_from_db()

        self.assertRedirects(response, reverse("board:post_detail", args=[post.pk]))
        self.assertEqual(post.title, "管理员更新")


class PostGalleryDisplayTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        cls.addClassCleanup(settings.disable)

    def setUp(self):
        self.user = User.objects.create_user("gallery-viewer")
        self.client.force_login(self.user)

    @staticmethod
    def image_upload(name):
        data = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(data, "PNG")
        return SimpleUploadedFile(name, data.getvalue(), "image/png")

    def create_gallery_post(self):
        post = Post.objects.create(author=self.user, title="展示多图", body="正文内容", kind="showcase")
        cover = PostImage.objects.create(post=post, image=self.image_upload("封面.png"), is_cover=True)
        other = PostImage.objects.create(post=post, image=self.image_upload("另一张.png"))
        return post, cover, other

    def test_card_uses_only_selected_cover_and_detail_places_cover_before_body(self):
        post, cover, other = self.create_gallery_post()
        # Pages show display-size thumbnails; the original stays one click away.
        cover_url = reverse("board:post_gallery_thumb", args=[post.pk, cover.pk])
        other_url = reverse("board:post_gallery_thumb", args=[post.pk, other.pk])

        card = self.client.get(reverse("board:home")).content.decode()
        detail = self.client.get(reverse("board:post_detail", args=[post.pk])).content.decode()

        self.assertIn(cover_url, card)
        self.assertNotIn(other_url, card)
        self.assertLess(detail.index(cover_url), detail.index("正文内容"))
        self.assertIn(other_url, detail)
        self.assertNotEqual(cover.pk, other.pk)

    def test_home_card_has_expandable_full_body_and_detail_link(self):
        post, _, _ = self.create_gallery_post()
        post.body = "首段" + "长正文" * 100
        post.save(update_fields=["body"])

        response = self.client.get(reverse("board:home"))

        self.assertContains(response, "data-post-expand")
        self.assertContains(response, f'id="post-full-{post.pk}"')
        self.assertContains(response, "展开全文")
        self.assertNotContains(response, "查看详情")  # 标题和整张卡片都能点进详情
        self.assertContains(response, reverse("board:post_detail", args=[post.pk]))

    def test_home_card_assets_define_expand_and_compact_cover_behavior(self):
        app_js = Path(settings.BASE_DIR / "static/board/app.js").read_text()
        app_css = Path(settings.BASE_DIR / "static/board/app.css").read_text()

        self.assertIn("data-post-expand", app_js)
        self.assertIn("aria-expanded", app_js)
        self.assertIn("post-full-body", app_css)
        self.assertIn(".post-image-preview img", app_css)
        self.assertIn("height:220px", app_css)

    def test_gallery_image_requires_login_and_belongs_to_post(self):
        post, _, image = self.create_gallery_post()
        url = reverse("board:post_gallery_image", args=[post.pk, image.pk])

        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_comment_form_omits_admin_identity_note(self):
        post, _, _ = self.create_gallery_post()

        response = self.client.get(reverse("board:post_detail", args=[post.pk]))

        self.assertNotContains(response, "匿名身份仅管理员可查看")

    def test_public_pages_omit_anonymous_identity_explanations(self):
        for response in (self.client.get(reverse("board:home")), self.client.get(reverse("board:post_create"))):
            self.assertNotContains(response, "匿名内容的作者身份仅管理员可查看")
            self.assertNotContains(response, "其他同学看不到你的身份")


class PostGalleryAdminTests(TestCase):
    def test_admin_registers_post_images_without_post_inline_formset(self):
        self.assertIn(PostImage, admin.site._registry)
        self.assertNotIn(PostImage, [inline.model for inline in admin.site._registry[Post].inlines])
