"""Markdown sharing through the same student-facing requests as normal posts."""
import hashlib
import tempfile
from pathlib import Path
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from .models import Post, Resource, Ticket


class MarkdownSharingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user('md-student', password='test-only-password', first_name='作者真实姓名')
        cls.other = User.objects.create_user('md-reader', password='test-only-password')
        cls.teacher = User.objects.create_user('md-teacher', is_staff=True)

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.client.force_login(self.student)

    def upload(self, text='# 学习笔记\n\n**重点**\n', name='学习笔记.md'):
        raw = text.encode() if isinstance(text, str) else text
        return SimpleUploadedFile(name, raw, content_type='text/markdown')

    def create(self, **extra):
        data = {'mode': 'showcase', 'body': '分享我的学习笔记', 'markdown_file': self.upload()}
        data.update(extra)
        response = self.client.post('/posts/quick/', data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Post.objects.count(), 1)
        post = Post.objects.get()
        self.assertTrue(getattr(post, 'markdown_file', None), 'Markdown file was not saved')
        return post

    def test_student_can_share_only_markdown_and_it_is_not_course_resource(self):
        post = self.create(body='', mode='topic')
        self.assertEqual(post.kind, 'showcase')
        self.assertEqual(post.title, '学习笔记')
        self.assertEqual(post.body, '')
        self.assertEqual(post.markdown_filename, '学习笔记.md')
        self.assertEqual(Resource.objects.count(), 0)
        self.assertContains(self.client.get('/?kind=showcase'), f'/posts/{post.pk}/markdown/read/')

    def test_full_editor_accepts_file_without_title_or_body_for_student_and_teacher(self):
        for user in [self.student, self.teacher]:
            self.client.force_login(user)
            response = self.client.post('/posts/new/', {'kind':'showcase','title':'','body':'','markdown_file': self.upload()})
            self.assertEqual(response.status_code, 302)
            post = Post.objects.filter(author=user).get()
            self.assertEqual(post.title, '学习笔记')
            self.assertTrue(post.markdown_file)

    def test_quick_duplicate_includes_file_bytes_and_original_name(self):
        first = self.create()
        self.client.post('/posts/quick/', {'mode':'showcase','body':first.body,'markdown_file':self.upload()})
        self.assertEqual(Post.objects.count(),1)
        self.client.post('/posts/quick/', {'mode':'showcase','body':first.body,'markdown_file':self.upload('# changed')})
        self.assertEqual(Post.objects.count(),2)
        self.client.post('/posts/quick/', {'mode':'showcase','body':first.body,'markdown_file':self.upload(name='another.md')})
        self.assertEqual(Post.objects.count(),3)
        self.client.post('/posts/quick/', {'mode':'showcase','body':first.body})
        self.assertEqual(Post.objects.count(),4)

    def test_reading_renders_markdown_safely_and_download_preserves_bytes(self):
        raw = '\ufeff# 标题\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n<script>alert(1)</script>\n[x](javascript:alert(1))\n'.encode()
        post = self.create(markdown_file=self.upload(raw))
        self.client.force_login(self.other)
        response = self.client.get(f'/posts/{post.pk}/markdown/read/')
        self.assertContains(response, '<h1>标题</h1>', html=True)
        self.assertContains(response, '<table>')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(response, 'href="javascript:')
        self.assertContains(response, '返回帖子')
        download = self.client.get(f'/posts/{post.pk}/markdown/download/')
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(download['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(b''.join(download.streaming_content), raw)
        self.assertEqual(post.markdown_sha256, hashlib.sha256(raw).hexdigest())

    def test_anonymous_reader_does_not_disclose_author(self):
        post = self.create(anonymous='on')
        self.client.force_login(self.other)
        response = self.client.get(f'/posts/{post.pk}/markdown/read/')
        self.assertContains(response, '匿名同学')
        self.assertNotContains(response, self.student.first_name)

    def test_unauthenticated_access_is_blocked(self):
        post = self.create()
        self.client.logout()
        for action in ['read','download']:
            self.assertEqual(self.client.get(f'/posts/{post.pk}/markdown/{action}/').status_code,302)

    def test_other_students_cannot_replace_or_remove(self):
        post = self.create()
        self.client.force_login(self.other)
        response = self.client.post(f'/posts/{post.pk}/edit/', {'kind':'showcase','title':post.title,'body':post.body,'markdown_file-clear':'on'})
        self.assertEqual(response.status_code,403)
        post.refresh_from_db()
        self.assertTrue(post.markdown_file)

    def test_author_can_replace_and_remove_attachment(self):
        post = self.create()
        data={'kind':'showcase','title':post.title,'body':post.body}
        response=self.client.post(f'/posts/{post.pk}/edit/', data | {'markdown_file':self.upload('# 新内容',name='新内容.markdown')})
        self.assertEqual(response.status_code,302)
        post.refresh_from_db()
        self.assertEqual(post.markdown_filename,'新内容.markdown')
        self.assertContains(self.client.get(f'/posts/{post.pk}/markdown/read/'),'<h1>新内容</h1>',html=True)
        response=self.client.post(f'/posts/{post.pk}/edit/',data | {'markdown_file-clear':'on'})
        self.assertEqual(response.status_code,302)
        post.refresh_from_db()
        self.assertFalse(post.markdown_file)
        self.assertEqual(post.markdown_filename,'')
        self.assertEqual(post.markdown_sha256,'')
        self.assertEqual(self.client.get(f'/posts/{post.pk}/markdown/download/').status_code,404)

    def test_file_only_post_cannot_become_empty_after_removal(self):
        post=self.create(body='')
        response=self.client.post(f'/posts/{post.pk}/edit/',{'kind':'showcase','title':post.title,'body':'','markdown_file-clear':'on'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'写点内容或添加 Markdown')
        post.refresh_from_db()
        self.assertTrue(post.markdown_file)

    def test_attachment_survives_edit_without_reselecting(self):
        post=self.create(body='')
        self.assertContains(self.client.get(f'/posts/{post.pk}/edit/'),f'/posts/{post.pk}/markdown/download/')
        response=self.client.post(f'/posts/{post.pk}/edit/',{'kind':'showcase','title':'改标题','body':''})
        self.assertEqual(response.status_code,302)
        post.refresh_from_db()
        self.assertTrue(post.markdown_file)

    def test_invalid_files_are_rejected_and_draft_preserved(self):
        cases=[('bad.txt',b'# text'),('bad.md',b'\xff\xfe'),('binary.md',b'abc\x00def'),('huge.md',b'x'*(2*1024*1024+1)),('empty.md',b''),('blank.md',b' \n')]
        for name,raw in cases:
            with self.subTest(name=name):
                response=self.client.post('/posts/quick/',{'mode':'showcase','body':'保留的文字','markdown_file':self.upload(raw,name)})
                self.assertEqual(response.status_code,302)
                self.assertEqual(Post.objects.count(),0)
                self.assertEqual(self.client.session['quick_draft']['body'],'保留的文字')

    def test_full_editor_rejects_invalid_file(self):
        response=self.client.post('/posts/new/',{'kind':'showcase','title':'测试','body':'说明','markdown_file':self.upload(b'\xff')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(Post.objects.count(),0)
        self.assertContains(response,'UTF-8')

    def test_private_question_cannot_leak_markdown_to_public_post(self):
        self.client.post('/posts/quick/',{'mode':'teacher','body':'私密问题','markdown_file':self.upload()})
        self.assertEqual(Post.objects.count(),0)
        self.assertEqual(Ticket.objects.count(),0)

    def test_missing_or_deleted_file_returns_404(self):
        post=self.create()
        Path(post.markdown_file.path).unlink()
        for action in ['read','download']:
            self.assertEqual(self.client.get(f'/posts/{post.pk}/markdown/{action}/').status_code,404)
        post.delete()
        self.assertEqual(self.client.get(f'/posts/{post.pk}/markdown/read/').status_code,404)

    def test_empty_normal_post_still_rejected(self):
        self.client.post('/posts/quick/',{'mode':'showcase','body':''})
        self.assertEqual(Post.objects.count(),0)
        response=self.client.post('/posts/new/',{'kind':'showcase','title':'空帖','body':''})
        self.assertEqual(response.status_code,200)
        self.assertEqual(Post.objects.count(),0)

    def test_upload_controls_are_available_to_students(self):
        for url in ['/','/posts/new/?kind=showcase']:
            response=self.client.get(url)
            self.assertContains(response,'name="markdown_file"')
            self.assertContains(response,'添加 Markdown')

    def test_remove_checkbox_is_preserved_after_unrelated_validation_error(self):
        post=self.create()
        response=self.client.post(f'/posts/{post.pk}/edit/',{'kind':'showcase','title':post.title,'body':post.body,'markdown_file-clear':'on','link':'invalid'})
        self.assertEqual(response.status_code,200)
        from html.parser import HTMLParser
        class Inputs(HTMLParser):
            def handle_starttag(parser,tag,attrs):
                attrs=dict(attrs)
                if tag == 'input' and attrs.get('name') == 'markdown_file-clear':
                    parser.clear=attrs
        parser=Inputs();parser.feed(response.content.decode())
        self.assertIn('checked',parser.clear)
        self.assertContains(response,'data-markdown-existing="true"')
