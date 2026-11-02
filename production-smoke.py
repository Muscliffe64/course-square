import os,io,tempfile
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client,override_settings
from board.models import Post,PostImage

before=(Post.objects.count(),PostImage.objects.count())
with tempfile.TemporaryDirectory(prefix='quick-images-smoke-') as media:
    with override_settings(MEDIA_ROOT=media), transaction.atomic():
        client=Client(enforce_csrf_checks=True)
        client.force_login(User.objects.filter(is_staff=True,is_active=True).first())
        options={'secure':True,'HTTP_HOST':'123.57.56.38'}
        home=client.get('/',**options)
        assert home.status_code==200 and b'data-image-input' in home.content
        csrf=client.cookies['csrftoken'].value
        data=io.BytesIO();Image.new('RGB',(2,2),'green').save(data,'PNG')
        upload=SimpleUploadedFile('smoke.png',data.getvalue(),'image/png')
        result=client.post('/posts/quick/',{'mode':'showcase','body':'Temporary image upload verification','images':[upload],'csrfmiddlewaretoken':csrf},HTTP_REFERER='https://123.57.56.38/',**options)
        assert result.status_code==302, result.status_code
        post=Post.objects.get(body='Temporary image upload verification')
        assert post.gallery_images.count()==1 and post.cover_image.is_cover
        assert post.cover_image.thumbnail
        with post.cover_image.image.open('rb') as stored: assert stored.read()==data.getvalue()
        denied=client.post('/posts/quick/',{'mode':'showcase','body':'missing csrf'},**options)
        assert denied.status_code==403
        print('Production configuration: authenticated multipart image save, cover, thumbnail and CSRF checks passed.')
        transaction.set_rollback(True)
assert (Post.objects.count(),PostImage.objects.count())==before
print('Database rolled back; no verification posts or images remain.')
