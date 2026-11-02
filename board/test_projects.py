import tempfile
from pathlib import Path
import io
from PIL import Image
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from .models import Post

MP4 = (Path(__file__).parent / 'fixtures/project-test.mp4').read_bytes()
def video(name='demo.mp4', data=MP4):
    return SimpleUploadedFile(name, data, 'video/mp4')

class ProjectTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        media = tempfile.TemporaryDirectory(); cls.addClassCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name); settings.enable(); cls.addClassCleanup(settings.disable)
    def setUp(self):
        self.owner = User.objects.create_user('owner'); self.client.force_login(self.owner)
    def payload(self, **extra):
        return {'title':'项目帖', 'body':'总介绍', 'kind':'showcase', 'closing_body':'来源与问题',
                'projects-TOTAL_FORMS':'1', 'projects-INITIAL_FORMS':'0',
                'projects-0-title':'作品 A', 'projects-0-description':'作品介绍',
                'projects-0-position':'1', 'projects-0-video':video(), **extra}
    def create(self):
        response = self.client.post(reverse('board:post_create'), self.payload())
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(); self.assertEqual(post.projects.count(), 1)
        return post, post.projects.get()
    def test_upload_and_ordered_inline_detail(self):
        post, project = self.create()
        html = self.client.get(reverse('board:post_detail', args=[post.pk])).content.decode()
        self.assertIn('<video', html); self.assertIn('preload="none"', html)
        self.assertLess(html.index('总介绍'), html.index('作品介绍'))
        self.assertLess(html.index('作品介绍'), html.index('来源与问题'))
    def test_invalid_upload_is_atomic(self):
        for upload in (video('bad.txt'), video(data=b'not mp4')):
            response = self.client.post(reverse('board:post_create'), self.payload(**{'projects-0-video': upload}))
            self.assertEqual(response.status_code, 200); self.assertFalse(Post.objects.exists())
    def test_missing_video_is_atomic(self):
        data = self.payload(); del data['projects-0-video']
        response = self.client.post(reverse('board:post_create'), data)
        self.assertEqual(response.status_code, 200); self.assertFalse(Post.objects.exists())
    def test_blank_row_ignored(self):
        data = self.payload(); data.update({'projects-0-title':'', 'projects-0-description':'', 'projects-0-position':'1'}); del data['projects-0-video']
        response = self.client.post(reverse('board:post_create'), data)
        self.assertEqual(response.status_code, 302); self.assertEqual(Post.objects.get().projects.count(),0)
    def test_legacy_edit_preserves_media(self):
        post, project = self.create(); name = project.video.name
        response = self.client.post(reverse('board:post_edit', args=[post.pk]), {'title':'改题','body':'改文','kind':'showcase'})
        self.assertEqual(response.status_code,302); project.refresh_from_db(); self.assertEqual(project.video.name,name)
    def test_text_edit_preserves_media_and_delete(self):
        post, project = self.create(); data=self.payload(**{'projects-INITIAL_FORMS':'1', 'projects-0-id':str(project.pk), 'projects-0-title':'更新'})
        del data['projects-0-video']; url=reverse('board:post_edit',args=[post.pk])
        self.assertEqual(self.client.post(url,data).status_code,302); project.refresh_from_db(); self.assertEqual(project.title,'更新')
        data['projects-0-DELETE']='on'; self.assertEqual(self.client.post(url,data).status_code,302); self.assertFalse(post.projects.exists())
    def test_nonowner_cannot_edit(self):
        post, _ = self.create(); self.client.force_login(User.objects.create_user('other'))
        self.assertEqual(self.client.post(reverse('board:post_edit',args=[post.pk]),self.payload()).status_code,403)
    def test_foreign_id_rejected(self):
        post, project = self.create(); other=Post.objects.create(author=self.owner,title='other',body='body',kind='showcase')
        data=self.payload(**{'projects-INITIAL_FORMS':'1','projects-0-id':str(project.pk)}); del data['projects-0-video']
        response=self.client.post(reverse('board:post_edit',args=[other.pk]),data)
        self.assertEqual(response.status_code,200); self.assertFalse(other.projects.exists())
    def test_stream_ranges_auth_and_parent_scope(self):
        post, project=self.create(); url=reverse('board:post_project_video',args=[post.pk,project.pk])
        for range_value, status, expected in [('',200,MP4),('bytes=4-11',206,MP4[4:12]),('bytes=4-',206,MP4[4:]),('bytes=-4',206,MP4[-4:]),('bytes=0-1,4-5',200,MP4)]:
            response=self.client.get(url,HTTP_RANGE=range_value); self.assertEqual(response.status_code,status)
            self.assertEqual(int(response['Content-Length']),len(expected)); self.assertEqual(b''.join(response.streaming_content),expected); response.close()
        for value in (f'bytes={len(MP4)+1}-', 'bytes=5-2', 'bytes=x-y', 'bytes=-0', 'bytes=' + '9'*5000 + '-'):
            response=self.client.get(url,HTTP_RANGE=value); self.assertEqual(response.status_code,416); self.assertEqual(response['Content-Range'],f'bytes */{len(MP4)}')
        response=self.client.head(url,HTTP_RANGE='bytes=4-11'); self.assertEqual(response.status_code,206); self.assertEqual(response.content,b'')
        self.assertEqual(self.client.get(reverse('board:post_project_video',args=[post.pk+1,project.pk])).status_code,404)
        self.client.logout(); self.assertEqual(self.client.get(url).status_code,302)
    def test_missing_file_returns_404(self):
        post, project=self.create(); project.video.storage.delete(project.video.name)
        self.assertEqual(self.client.get(reverse('board:post_project_video',args=[post.pk,project.pk])).status_code,404)

    def test_cap_and_bound_error_data(self):
        data = self.payload(**{'projects-TOTAL_FORMS':'11'})
        for i in range(1,11):
            data.update({f'projects-{i}-title':f'作品 {i}',f'projects-{i}-description':'介绍',f'projects-{i}-position':str(i),f'projects-{i}-video':video()})
        response = self.client.post(reverse('board:post_create'),data)
        self.assertEqual(response.status_code,200); self.assertFalse(Post.objects.exists())
        self.assertContains(response,'作品 10'); self.assertContains(response,'10')
    def test_post_error_does_not_save_projects(self):
        response=self.client.post(reverse('board:post_create'),self.payload(title=''))
        self.assertEqual(response.status_code,200); self.assertFalse(Post.objects.exists())
    def ten_project_post(self):
        from .models import PostProject
        post, project = self.create()
        for i in range(1, 10):
            PostProject.objects.create(post=post, title=f'作品 {i}', description='介绍',
                                       position=i, video=video())
        return post, project

    def test_forged_initial_count_cannot_add_eleventh_project(self):
        post, _ = self.ten_project_post()
        response = self.client.post(reverse('board:post_edit', args=[post.pk]), self.payload())
        self.assertEqual(post.projects.count(), 10)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '一条内容最多添加 10 个项目。')

    def test_partial_edit_retains_unsubmitted_existing_projects(self):
        post, project = self.ten_project_post()
        data = self.payload(**{'projects-INITIAL_FORMS':'1',
                               'projects-0-id':str(project.pk), 'projects-0-title':'更新'})
        del data['projects-0-video']
        original_ids = set(post.projects.values_list('pk', flat=True))
        response = self.client.post(reverse('board:post_edit', args=[post.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(post.projects.values_list('pk', flat=True)), original_ids)
        project.refresh_from_db(); self.assertEqual(project.title, '更新')

    def test_full_edit_at_cap_preserves_all_projects(self):
        post, _ = self.ten_project_post()
        data = self.payload(**{'projects-TOTAL_FORMS':'10', 'projects-INITIAL_FORMS':'10'})
        del data['projects-0-video']
        original_ids = set(post.projects.values_list('pk', flat=True))
        for i, project in enumerate(post.projects.all()):
            data.update({f'projects-{i}-id':str(project.pk),
                         f'projects-{i}-title':f'更新 {i}',
                         f'projects-{i}-description':project.description,
                         f'projects-{i}-position':str(project.position)})
        response = self.client.post(reverse('board:post_edit', args=[post.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(post.projects.values_list('pk', flat=True)), original_ids)
        self.assertEqual(post.projects.filter(title__startswith='更新 ').count(), 10)

    def test_partial_delete_and_replace_at_cap(self):
        post, project = self.ten_project_post()
        data = self.payload(**{'projects-TOTAL_FORMS':'2', 'projects-INITIAL_FORMS':'1',
                               'projects-0-id':str(project.pk), 'projects-0-DELETE':'on',
                               'projects-1-title':'替换', 'projects-1-description':'介绍',
                               'projects-1-position':'10', 'projects-1-video':video()})
        del data['projects-0-video']
        response = self.client.post(reverse('board:post_edit', args=[post.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(post.projects.count(), 10)
        self.assertFalse(post.projects.filter(pk=project.pk).exists())
        self.assertTrue(post.projects.filter(title='替换').exists())

    def test_extra_form_delete_cannot_discount_existing_project(self):
        post, project = self.ten_project_post()
        data = self.payload(**{'projects-TOTAL_FORMS':'2',
                               'projects-0-id':str(project.pk), 'projects-0-DELETE':'on',
                               'projects-1-title':'新增', 'projects-1-description':'介绍',
                               'projects-1-position':'10', 'projects-1-video':video()})
        del data['projects-0-video']
        response = self.client.post(reverse('board:post_edit', args=[post.pk]), data)
        self.assertEqual(post.projects.count(), 10)
        self.assertEqual(response.status_code, 200)
    def test_poster_validation_and_private_stream(self):
        image = io.BytesIO(); Image.new('RGB',(2,2),'red').save(image,'PNG')
        response=self.client.post(reverse('board:post_create'),self.payload(**{'projects-0-poster':SimpleUploadedFile('cover.png',image.getvalue(),'image/png')}))
        self.assertEqual(response.status_code,302); post=Post.objects.get(); project=post.projects.get()
        url=reverse('board:post_project_poster',args=[post.pk,project.pk]); response=self.client.get(url)
        self.assertEqual(response['Content-Type'],'image/png'); self.assertIn('private',response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content),image.getvalue()); response.close()
        self.assertEqual(self.client.get(reverse('board:post_project_poster',args=[post.pk+1,project.pk])).status_code,404)
        self.client.logout(); self.assertEqual(self.client.get(url).status_code,302)
    def test_invalid_poster_atomic(self):
        response=self.client.post(reverse('board:post_create'),self.payload(**{'projects-0-poster':SimpleUploadedFile('cover.png',b'bad')}))
        self.assertEqual(response.status_code,200); self.assertFalse(Post.objects.exists())
    def test_media_requests_skip_visit_log(self):
        from .models import VisitLog
        post,project=self.create(); before=VisitLog.objects.count()
        response=self.client.get(reverse('board:post_project_video',args=[post.pk,project.pk]),HTTP_RANGE='bytes=0-10')
        self.assertEqual(b''.join(response.streaming_content),MP4[:11]); response.close()
        self.assertEqual(VisitLog.objects.count(),before)
    def test_order_and_escaping_and_gallery_suppression(self):
        from .models import PostProject
        post,project=self.create()
        PostProject.objects.create(post=post,title='<b>First</b>',description='<script>bad</script>',position=0,video=video())
        post.image='post-images/cover.png'; post.save()
        response=self.client.get(reverse('board:post_detail',args=[post.pk])); html=response.content.decode()
        self.assertLess(html.index('&lt;b&gt;First'),html.index('作品 A'))
        self.assertContains(response,'&lt;script&gt;bad&lt;/script&gt;'); self.assertNotContains(response,'class="detail-image"')

class ProjectValidationTests(TestCase):
    def test_previous_post_model_can_insert_after_schema_upgrade(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        old_apps = MigrationExecutor(connection).loader.project_state(
            [('board', '0012_ticket_replies')]).apps
        old_post = old_apps.get_model('board', 'Post')
        owner = User.objects.create_user('historical-owner')
        created = old_post.objects.create(author_id=owner.pk, title='旧版创建',
                                          body='旧版正文', kind='showcase')
        self.assertEqual(Post.objects.get(pk=created.pk).closing_body, '')

    def test_video_size_and_reset_and_fake_ftyp(self):
        from .projects import validate_video, MAX_VIDEO_BYTES
        self.assertEqual(MAX_VIDEO_BYTES,25*1024*1024)
        upload=video(); upload.size=MAX_VIDEO_BYTES; validate_video(upload); self.assertEqual(upload.tell(),0)
        upload.size+=1
        with self.assertRaises(ValidationError): validate_video(upload)
        self.assertEqual(upload.tell(),0)
        with self.assertRaises(ValidationError): validate_video(video(data=b'\x00\x00\x00\xffftypisom0000'))
    def test_combined_budget_includes_parent_and_admin(self):
        from .projects import ProjectFormSet, MAX_PROJECT_UPLOAD_BYTES
        data={'projects-TOTAL_FORMS':'1','projects-INITIAL_FORMS':'0','projects-0-title':'A','projects-0-description':'B','projects-0-position':'1'}
        uploads=[]
        for i in range(3):
            upload=video(); upload.size=25*1024*1024 if i<2 else 15*1024*1024; uploads.append(upload)
        files=MultiValueDict({'projects-0-video':[uploads[0]],'audio':[uploads[1]],'images':[uploads[2]]})
        formset=ProjectFormSet(data,files,prefix='projects',instance=Post())
        self.assertFalse(formset.is_valid()); self.assertIn('64 MB',str(formset.non_form_errors()))
        uploads[2].size=14*1024*1024; formset=ProjectFormSet(data,files,prefix='projects',instance=Post())
        self.assertTrue(formset.is_valid(),formset.errors)
    def test_admin_inline_uses_shared_validation(self):
        from django.contrib import admin
        from .models import PostProject
        from .projects import BaseProjectFormSet, ProjectForm
        inline=admin.site._registry[Post].inlines[0]
        self.assertEqual(inline.model,PostProject); self.assertEqual(inline.form,ProjectForm); self.assertEqual(inline.formset,BaseProjectFormSet)


class ProjectEditTransactionTests(TransactionTestCase):
    def test_stale_additions_validate_under_write_transaction(self):
        from unittest.mock import patch
        from django.db import connection
        from .models import PostProject
        from .projects import BaseProjectFormSet
        owner = User.objects.create_user('concurrent-owner')
        self.client.force_login(owner)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            post = Post.objects.create(author=owner, title='项目帖', body='介绍', kind='showcase')
            for i in range(9):
                PostProject.objects.create(post=post, title=f'项目 {i}', description='介绍',
                                           position=i, video=video())
            # Both editors opened the same nine children before either submitted.
            stale_rows = list(post.projects.all())
            def submission(title):
                data = {'title':'项目帖', 'body':'介绍', 'kind':'showcase',
                        'projects-TOTAL_FORMS':'10', 'projects-INITIAL_FORMS':'9',
                        'projects-9-title':title, 'projects-9-description':'新增介绍',
                        'projects-9-position':'9', 'projects-9-video':video()}
                for i, project in enumerate(stale_rows):
                    data.update({f'projects-{i}-id':str(project.pk),
                                 f'projects-{i}-title':project.title,
                                 f'projects-{i}-description':project.description,
                                 f'projects-{i}-position':str(project.position)})
                return data
            observations = []
            clean = BaseProjectFormSet.clean
            def record_validation(formset):
                observations.append((connection.in_atomic_block,
                                     formset.get_queryset().count()))
                return clean(formset)
            url = reverse('board:post_edit', args=[post.pk])
            with patch.object(BaseProjectFormSet, 'clean', record_validation):
                first = self.client.post(url, submission('编辑器 A'))
                second = self.client.post(url, submission('编辑器 B'))
            self.assertEqual(observations, [(True, 9), (True, 10)])
            self.assertEqual(first.status_code, 302)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(post.projects.count(), 10)
            self.assertFalse(post.projects.filter(title='编辑器 B').exists())
