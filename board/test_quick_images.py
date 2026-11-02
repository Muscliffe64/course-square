import io
import tempfile
from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Post, Ticket

class QuickImageTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        media = tempfile.TemporaryDirectory(); cls.addClassCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable(); cls.addClassCleanup(settings.disable)

    def setUp(self):
        self.user = User.objects.create_user('quick-images')
        self.client.force_login(self.user)
        self.url = reverse('board:quick_post')

    def image(self, name='图片.png', color='red'):
        data=io.BytesIO(); Image.new('RGB',(2,2),color).save(data,'PNG')
        return SimpleUploadedFile(name,data.getvalue(),'image/png')

    def publish(self, images=(), **extra):
        data={'mode':'showcase','body':'我的图文分享','images':list(images)}; data.update(extra)
        return self.client.post(self.url,data)

    def test_quick_post_saves_gallery_and_first_cover(self):
        response=self.publish([self.image('第一张.png'),self.image('第二张.png')],anonymous='on')
        self.assertEqual(response.status_code,302)
        post=Post.objects.get(); gallery=list(post.gallery_images.all())
        self.assertEqual(len(gallery),2); self.assertEqual(post.kind,'showcase')
        self.assertEqual(post.title,'我的图文分享'); self.assertTrue(post.anonymous)
        self.assertEqual(post.cover_image.original_filename,'第一张.png')
        self.assertTrue(all(item.thumbnail for item in gallery))

    def test_rejects_nine_images_and_preserves_text_draft(self):
        self.publish([self.image(f'{i}.png') for i in range(9)])
        self.assertFalse(Post.objects.exists())
        self.assertEqual(self.client.session['quick_draft']['body'],'我的图文分享')

    def test_invalid_image_does_not_create_post(self):
        self.publish([SimpleUploadedFile('bad.png',b'not an image','image/png')])
        self.assertFalse(Post.objects.exists())

    def test_oversized_image_does_not_create_post(self):
        upload=self.image(); upload.file=io.BytesIO(upload.read()+b'0'*(8*1024*1024)); upload.size=8*1024*1024+100
        self.publish([upload]); self.assertFalse(Post.objects.exists())

    def test_private_ticket_rejects_images(self):
        self.publish([self.image()],mode='teacher')
        self.assertFalse(Ticket.objects.exists()); self.assertFalse(Post.objects.exists())

    def test_legacy_private_flag_rejects_images(self):
        self.publish([self.image()],to_teacher='on')
        self.assertFalse(Ticket.objects.exists()); self.assertFalse(Post.objects.exists())

    def test_identical_retry_does_not_duplicate_post_or_images(self):
        for _ in range(2): self.publish([self.image()])
        self.assertEqual(Post.objects.count(),1)
        self.assertEqual(Post.objects.get().gallery_images.count(),1)

    def test_same_body_with_changed_image_is_not_discarded(self):
        self.publish([self.image(color='red')]); self.publish([self.image(color='blue')])
        self.assertEqual(Post.objects.count(),2)

    def test_image_post_after_text_post_is_not_discarded(self):
        self.publish(); self.publish([self.image()])
        self.assertEqual(Post.objects.count(),2)
        self.assertEqual(sum(p.gallery_images.count() for p in Post.objects.all()),1)

    def test_text_post_after_image_post_is_not_discarded(self):
        self.publish([self.image()]); self.publish()
        self.assertEqual(Post.objects.count(),2)

    def test_home_composer_accepts_multipart_images(self):
        response=self.client.get(reverse('board:home'))
        self.assertContains(response,'enctype="multipart/form-data"')
        self.assertContains(response,'data-image-input'); self.assertContains(response,'image-picker.js')

    def test_unauthenticated_upload_cannot_publish(self):
        self.client.logout(); response=self.publish([self.image()])
        self.assertEqual(response.status_code,302); self.assertFalse(Post.objects.exists())
