from pathlib import Path

import board.models
from django.db import migrations, models


def copy_legacy_images(apps, schema_editor):
    Post = apps.get_model("board", "Post")
    PostImage = apps.get_model("board", "PostImage")
    for post in Post.objects.exclude(image=""):
        PostImage.objects.create(
            post_id=post.pk,
            image=post.image.name,
            original_filename=(post.image_original_filename or Path(post.image.name).name)[:255],
            is_cover=True,
        )


class Migration(migrations.Migration):
    dependencies = [("board", "0005_post_original_filenames")]

    operations = [
        migrations.CreateModel(
            name="PostImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to=board.models.random_upload, validators=[board.models.validate_image], verbose_name="图片")),
                ("original_filename", models.CharField(blank=True, editable=False, max_length=255, verbose_name="图片原文件名")),
                ("is_cover", models.BooleanField(default=False, verbose_name="首页封面")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="上传时间")),
                ("post", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="gallery_images", to="board.post", verbose_name="帖子")),
            ],
            options={"verbose_name": "帖子图片", "verbose_name_plural": "帖子图片", "ordering": ["created_at", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="postimage",
            constraint=models.UniqueConstraint(condition=models.Q(("is_cover", True)), fields=("post",), name="one_cover_per_post"),
        ),
        migrations.RunPython(copy_legacy_images, migrations.RunPython.noop),
    ]
