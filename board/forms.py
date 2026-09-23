from django import forms
from .models import Comment, Post, PostImage, Report, validate_image


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleImageInput

    def clean(self, data, initial=None):
        if not data:
            return []
        uploads = data if isinstance(data, (list, tuple)) else [data]
        cleaned = []
        for upload in uploads:
            image = super().clean(upload, initial)
            validate_image(image)
            cleaned.append(image)
        return cleaned

class MediaUrlFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Original upload names have their own fields; storage may shorten its path.
        for field in ("image", "audio"):
            if field in self.fields:
                self.fields[field].max_length = 255

    def _clean_http_url(self, field):
        value = self.cleaned_data.get(field, "")
        if value and not value.lower().startswith(("http://", "https://")):
            raise forms.ValidationError("链接必须使用 http 或 https。")
        return value

    def clean_link(self):
        return self._clean_http_url("link")

    def clean_audio_link(self):
        return self._clean_http_url("audio_link")

    def clean_video_link(self):
        return self._clean_http_url("video_link")


class PostForm(MediaUrlFormMixin, forms.ModelForm):
    images = MultipleImageField(
        label="图片",
        required=False,
        help_text="可同时上传最多 8 张 JPEG、PNG 或 WebP 图片；请选择一张作为首页封面。",
        widget=MultipleImageInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )
    cover_choice = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            cover_image = self.instance.cover_image
            if cover_image:
                self.fields["cover_choice"].initial = f"existing:{cover_image.pk}"

    def clean_images(self):
        images = self.cleaned_data["images"]
        if len(images) > 8:
            raise forms.ValidationError("一次最多上传 8 张图片。")
        return images

    def clean_cover_choice(self):
        choice = self.cleaned_data.get("cover_choice", "")
        if not choice:
            return ""
        source, separator, identifier = choice.partition(":")
        if not separator or not identifier.isdigit():
            raise forms.ValidationError("请选择有效的首页封面。")
        if source == "new":
            if int(identifier) >= len(self.cleaned_data.get("images", [])):
                raise forms.ValidationError("请选择已上传图片中的一张作为首页封面。")
            return choice
        if source == "existing" and self.instance.pk and self.instance.gallery_images.filter(pk=int(identifier)).exists():
            return choice
        raise forms.ValidationError("请选择这条内容中的图片作为首页封面。")

    def save_gallery(self, post):
        created_images = [PostImage.objects.create(post=post, image=image) for image in self.cleaned_data["images"]]
        if post.image and not post.gallery_images.exists():
            created_images.append(PostImage.objects.create(
                post=post,
                image=post.image.name,
                original_filename=post.image_filename,
            ))

        choice = self.cleaned_data["cover_choice"]
        cover = None
        if choice.startswith("new:"):
            cover = created_images[int(choice.split(":", 1)[1])]
        elif choice.startswith("existing:"):
            cover = post.gallery_images.get(pk=int(choice.split(":", 1)[1]))
        elif not post.gallery_images.filter(is_cover=True).exists() and created_images:
            cover = created_images[0]

        if cover:
            post.gallery_images.filter(is_cover=True).exclude(pk=cover.pk).update(is_cover=False)
            PostImage.objects.filter(pk=cover.pk).update(is_cover=True)

    class Meta:
        model = Post
        fields = ["kind", "title", "body", "anonymous", "link", "image", "audio", "audio_link", "video_link"]
        labels = {"title": "标题", "body": "内容", "kind": "栏目", "anonymous": "匿名发布", "link": "作品链接", "image": "图片", "audio": "音频", "audio_link": "音频链接", "video_link": "视频链接"}
        help_texts = {
            "audio": "支持 MP3、M4A、WAV、OGG；文件会保留原始文件名和元数据。",
            "video_link": "视频仅支持填写链接，将在帖子详情页播放或打开。",
        }
        widgets = {"title": forms.TextInput(attrs={"placeholder": "简明概括你想讨论的内容（最多 120 字）"}), "body": forms.Textarea(attrs={"placeholder": "写下你的想法（最多 5000 字）"}), "link": forms.URLInput(attrs={"placeholder": "https://"}), "image": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}), "audio": forms.ClearableFileInput(attrs={"accept": "audio/mpeg,audio/mp4,audio/wav,audio/ogg"}), "audio_link": forms.URLInput(attrs={"placeholder": "https://"}), "video_link": forms.URLInput(attrs={"placeholder": "https://"})}

class PostAdminForm(MediaUrlFormMixin, forms.ModelForm):
    class Meta:
        model = Post
        fields = "__all__"

class CommentForm(forms.ModelForm):
    parent_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    class Meta:
        model = Comment
        fields = ["body", "anonymous"]
        labels = {"body": "评论", "anonymous": "匿名评论"}

class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ["reason"]
        labels = {"reason": "举报原因"}
