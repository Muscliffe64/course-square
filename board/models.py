import uuid
import warnings
from pathlib import Path
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from PIL import Image, UnidentifiedImageError
from .thumbnails import ensure_thumbnail, thumbnail_upload

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_RESOURCE_BYTES = 25 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_MARKDOWN_READ_BYTES = 2 * 1024 * 1024
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg"}

def random_upload(instance, filename):
    return f"post-images/{uuid.uuid4().hex}/{Path(filename).name}"

def random_resource_upload(instance, filename):
    return f"resources/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"

def random_audio_upload(instance, filename):
    return f"post-audio/{uuid.uuid4().hex}/{Path(filename).name}"

def validate_image(upload):
    if upload.size > MAX_IMAGE_BYTES:
        raise ValidationError("图片不能超过 8 MB。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(upload)
            image.verify()
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValidationError("仅支持 JPEG、PNG 和 WebP 图片。")
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError):
        raise ValidationError("上传的文件不是有效图片。")
    finally:
        upload.seek(0)

def validate_resource(upload):
    allowed = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".csv", ".zip"} | MARKDOWN_EXTENSIONS
    if upload.size > MAX_RESOURCE_BYTES:
        raise ValidationError("资料不能超过 25 MB。")
    if Path(upload.name).suffix.lower() not in allowed:
        raise ValidationError("不支持该资料格式。允许：PDF、Office 文档、TXT、CSV、Markdown、ZIP。")

def validate_audio(upload):
    if upload.size > MAX_AUDIO_BYTES:
        raise ValidationError("音频不能超过 25 MB。")
    if Path(upload.name).suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValidationError("仅支持 MP3、M4A、WAV 和 OGG 音频。")

class Post(models.Model):
    class Kind(models.TextChoices):
        TOPIC = "topic", "下节课想听什么"
        SHOWCASE = "showcase", "作品与分享"
    class Status(models.TextChoices):
        OPEN = "open", "开放"
        PLANNED = "planned", "已计划"
        ANSWERED = "answered", "已回应"
    author = models.ForeignKey(User, verbose_name="作者", on_delete=models.CASCADE, related_name="posts")
    title = models.CharField("标题", max_length=120)
    body = models.TextField("内容", max_length=5000)
    kind = models.CharField("栏目", max_length=16, choices=Kind.choices)
    anonymous = models.BooleanField("匿名", default=False)
    link = models.URLField("链接", max_length=500, blank=True)
    image = models.ImageField("图片", upload_to=random_upload, validators=[validate_image], blank=True)
    image_original_filename = models.CharField("图片原文件名", max_length=255, blank=True, editable=False)
    audio = models.FileField("音频", upload_to=random_audio_upload, validators=[validate_audio], blank=True)
    audio_original_filename = models.CharField("音频原文件名", max_length=255, blank=True, editable=False)
    audio_link = models.URLField("音频链接", max_length=500, blank=True)
    video_link = models.URLField("视频链接", max_length=500, blank=True)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.OPEN)
    pinned = models.BooleanField("置顶", default=False)
    created_at = models.DateTimeField("发布时间", auto_now_add=True)
    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
        for field in ("image", "audio"):
            upload = getattr(self, field)
            if upload and not upload._committed and (update_fields is None or field in update_fields):
                original_field = f"{field}_original_filename"
                setattr(self, original_field, Path(upload.name).name)
                if update_fields is not None:
                    update_fields.add(original_field)
        if update_fields is not None:
            kwargs["update_fields"] = update_fields
        super().save(*args, **kwargs)
    @property
    def image_filename(self):
        return self.image_original_filename or Path(self.image.name or "").name

    @property
    def cover_image(self):
        gallery_images = getattr(self, "_prefetched_objects_cache", {}).get("gallery_images")
        if gallery_images is not None:
            return next((image for image in gallery_images if image.is_cover), None)
        return self.gallery_images.filter(is_cover=True).first()

    @property
    def cover_image_file(self):
        cover_image = self.cover_image
        return cover_image.image if cover_image else self.image

    @property
    def cover_image_filename(self):
        cover_image = self.cover_image
        return cover_image.original_filename if cover_image else self.image_filename
    @property
    def audio_filename(self):
        return self.audio_original_filename or Path(self.audio.name or "").name
    def __str__(self): return self.title
    class Meta:
        ordering = ["-pinned", "-created_at"]
        verbose_name = "帖子"
        verbose_name_plural = "帖子"


class PostImage(models.Model):
    post = models.ForeignKey(Post, verbose_name="帖子", on_delete=models.CASCADE, related_name="gallery_images")
    image = models.ImageField("图片", upload_to=random_upload, validators=[validate_image])
    original_filename = models.CharField("图片原文件名", max_length=255, blank=True, editable=False)
    thumbnail = models.ImageField("缩略图", upload_to=thumbnail_upload, blank=True, editable=False)
    is_cover = models.BooleanField("首页封面", default=False)
    created_at = models.DateTimeField("上传时间", auto_now_add=True)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.image and not self.image._committed and (update_fields is None or "image" in update_fields):
            self.original_filename = Path(self.image.name).name
            self.thumbnail = ""  # a replaced image needs a new thumbnail
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"original_filename", "thumbnail"}
        super().save(*args, **kwargs)
        ensure_thumbnail(self)

    def __str__(self):
        return self.original_filename or Path(self.image.name or "").name or f"图片 {self.pk}"

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [models.UniqueConstraint(
            fields=["post"], condition=models.Q(is_cover=True), name="one_cover_per_post",
        )]
        verbose_name = "帖子图片"
        verbose_name_plural = "帖子图片"

class Comment(models.Model):
    post = models.ForeignKey(Post, verbose_name="帖子", on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", verbose_name="回复对象", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    author = models.ForeignKey(User, verbose_name="作者", on_delete=models.CASCADE, related_name="comments")
    body = models.TextField("内容", max_length=1000)
    anonymous = models.BooleanField("匿名", default=False)
    created_at = models.DateTimeField("发布时间", auto_now_add=True)
    def __str__(self): return f"{self.post}: {self.body[:30]}"
    class Meta:
        ordering = ["created_at"]
        verbose_name = "评论"
        verbose_name_plural = "评论"

class Notification(models.Model):
    class Kind(models.TextChoices):
        NEW_COMMENT = "new_comment", "学生新留言"
        COMMENT_REPLY = "comment_reply", "评论被回复"
        POST_LIKE = "post_like", "帖子获赞"
    recipient = models.ForeignKey(User, verbose_name="接收人", on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(User, verbose_name="触发人", on_delete=models.SET_NULL, null=True, related_name="sent_notifications")
    kind = models.CharField("类型", max_length=24, choices=Kind.choices)
    post = models.ForeignKey(Post, verbose_name="帖子", on_delete=models.CASCADE, related_name="notifications")
    comment = models.ForeignKey(Comment, verbose_name="评论", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications")
    # Fixed at creation: the comment may be deleted later, and its anonymity must survive that.
    actor_anonymous = models.BooleanField("触发人匿名", default=False)
    created_at = models.DateTimeField("时间", auto_now_add=True)
    read_at = models.DateTimeField("已读时间", null=True, blank=True)
    class Meta:
        ordering = ["-created_at"]
        verbose_name = "站内通知"
        verbose_name_plural = "站内通知"

class Like(models.Model):
    post = models.ForeignKey(Post, verbose_name="帖子", on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(User, verbose_name="用户", on_delete=models.CASCADE, related_name="likes")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="unique_post_like")]
        verbose_name = "点赞"
        verbose_name_plural = "点赞"
    def __str__(self): return f"{self.user.first_name or self.user_id} → {self.post}"

class Resource(models.Model):
    title = models.CharField("标题", max_length=120)
    description = models.TextField("说明", max_length=1000, blank=True)
    category = models.CharField("分类", max_length=80, blank=True)
    file = models.FileField("文件", upload_to=random_resource_upload, validators=[validate_resource])
    original_filename = models.CharField("原文件名", max_length=255, blank=True, editable=False)
    created_at = models.DateTimeField("上传时间", auto_now_add=True)
    def save(self, *args, **kwargs):
        if self.file and not self.file._committed:
            self.original_filename = Path(self.file.name).name
        super().save(*args, **kwargs)
    @property
    def is_markdown(self):
        return Path(self.original_filename or self.file.name).suffix.lower() in MARKDOWN_EXTENSIONS
    class Meta:
        ordering = ["-created_at"]
        verbose_name = "课程资料"
        verbose_name_plural = "课程资料"
    def __str__(self): return f"{self.title}（{self.category}）" if self.category else self.title

class Announcement(models.Model):
    title = models.CharField("标题", max_length=120)
    body = models.TextField("内容", max_length=3000)
    active = models.BooleanField("启用", default=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "教师公告"
        verbose_name_plural = "教师公告"
    def __str__(self): return self.title

class Report(models.Model):
    post = models.ForeignKey(Post, verbose_name="帖子", on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(User, verbose_name="举报人", on_delete=models.CASCADE, related_name="reports")
    reason = models.TextField("原因", max_length=500)
    created_at = models.DateTimeField("举报时间", auto_now_add=True)
    resolved = models.BooleanField("已处理", default=False)
    def __str__(self): return f"{self.post}: {self.reason[:30]}"
    class Meta:
        verbose_name = "举报"
        verbose_name_plural = "举报"

class LoginAttempt(models.Model):
    username = models.CharField("用户名", max_length=150)
    ip_address = models.GenericIPAddressField("IP 地址", null=True, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=["username", "ip_address", "created_at"])]
        verbose_name = "登录失败记录"
        verbose_name_plural = "登录失败记录"
    def __str__(self): return f"{self.username} @ {self.created_at:%F %T}"

class VisitLog(models.Model):
    user = models.ForeignKey(User, verbose_name="用户", on_delete=models.SET_NULL, null=True, blank=True, related_name="visits")
    ip_address = models.GenericIPAddressField("IP 地址", null=True, blank=True)
    path = models.CharField("访问路径", max_length=300)
    created_at = models.DateTimeField("时间", auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=["ip_address", "created_at"]), models.Index(fields=["created_at"])]
        verbose_name = "访问记录"
        verbose_name_plural = "访问记录"
    def __str__(self): return f"{self.ip_address or '-'} {self.path} @ {self.created_at:%F %T}"
