from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("board", "0004_post_audio_audio_link_video_link")]

    operations = [
        migrations.AddField(
            model_name="post", name="image_original_filename",
            field=models.CharField(blank=True, editable=False, max_length=255, verbose_name="图片原文件名"),
        ),
        migrations.AddField(
            model_name="post", name="audio_original_filename",
            field=models.CharField(blank=True, editable=False, max_length=255, verbose_name="音频原文件名"),
        ),
    ]
