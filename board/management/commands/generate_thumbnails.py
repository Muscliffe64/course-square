from django.core.management.base import BaseCommand

from board.models import PostImage
from board.thumbnails import ensure_thumbnail


class Command(BaseCommand):
    help = "为还没有缩略图的帖子图片生成缩略图（可重复执行，只处理缺失的）。"

    def handle(self, *args, **options):
        created = failed = 0
        for image in PostImage.objects.filter(thumbnail="").iterator():
            if ensure_thumbnail(image):
                created += 1
            else:
                failed += 1
        self.stdout.write(f"created={created} failed={failed}")
