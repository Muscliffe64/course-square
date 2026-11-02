"""Project upload validation shared by the full editor and admin inline."""
from pathlib import Path
from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

MAX_VIDEO_BYTES = 25 * 1024 * 1024
MAX_PROJECT_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_PROJECTS = 10

def validate_video(upload):
    try:
        if Path(upload.name).suffix.lower() != '.mp4':
            raise ValidationError('仅支持 MP4 视频。')
        if upload.size > MAX_VIDEO_BYTES:
            raise ValidationError('视频不能超过 25 MB。')
        header = upload.read(32)
        if len(header) < 16 or header[4:8] != b'ftyp' or not 16 <= int.from_bytes(header[:4], 'big') <= upload.size:
            raise ValidationError('上传的文件不是有效 MP4 容器。')
    finally:
        upload.seek(0)

def validate_upload_budget(files):
    """Count all newly submitted media, including the parent's images/audio."""
    names = list(files)
    project_media = any(name.endswith(('-video', '-poster')) and files.getlist(name) for name in names)
    if project_media and sum(file.size for name in names for file in files.getlist(name)) > MAX_PROJECT_UPLOAD_BYTES:
        raise ValidationError('本次上传的文件合计不能超过 64 MB。')

# Imported here to keep model validators importable without a circular import.
from .models import Post, PostProject

class ProjectForm(forms.ModelForm):
    class Meta:
        model = PostProject
        fields = ['title', 'description', 'creator', 'position', 'video', 'poster']
        widgets = {'description': forms.Textarea(attrs={'rows': 3}),
                   'video': forms.FileInput(attrs={'accept': 'video/mp4', 'data-max-bytes': MAX_VIDEO_BYTES}),
                   'poster': forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp', 'data-max-bytes': 8*1024*1024})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['video'].max_length = 255
        self.fields['poster'].max_length = 255
        # Empty optional rows must stay unchanged, including their order value.
        self.fields['position'].initial = None

    def has_changed(self):
        if not self.instance.pk and self.is_bound:
            content_fields = ('title', 'description', 'creator', 'video', 'poster')
            if not any(self.data.get(self.add_prefix(name), '').strip() or
                       self.files.get(self.add_prefix(name)) for name in content_fields):
                return False  # automatically assigned order alone is an empty row
        return super().has_changed()

class BaseProjectFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        validate_upload_budget(self.files)
        valid_ids = set(self.get_queryset().values_list('pk', flat=True))
        seen = set()
        for form in self.forms:
            identifier = form.data.get(form.add_prefix('id')) if form.is_bound else None
            if identifier:
                if not str(identifier).isdigit() or int(identifier) not in valid_ids or int(identifier) in seen:
                    raise ValidationError('项目必须属于当前帖子，且不能重复。')
                seen.add(int(identifier))
        if any(self.errors):
            return
        # Omitted existing rows survive save(). Only initial forms can delete
        # persisted children; an extra form's submitted id does not delete one.
        deleted_ids = {f.instance.pk for f in self.initial_forms
                       if f.cleaned_data.get('DELETE') and f.instance.pk in valid_ids}
        new_count = sum(1 for f in self.extra_forms
                        if f.has_changed() and not f.cleaned_data.get('DELETE'))
        if len(valid_ids - deleted_ids) + new_count > MAX_PROJECTS:
            raise ValidationError('一条内容最多添加 10 个项目。')

ProjectFormSet = inlineformset_factory(Post, PostProject, form=ProjectForm,
    formset=BaseProjectFormSet, extra=1, can_delete=True, max_num=MAX_PROJECTS,
    validate_max=True, absolute_max=100)


def project_formset_for_request(request, post):
    # Older full-editor clients do not submit inline management data.
    bound = request.method == "POST" and "projects-TOTAL_FORMS" in request.POST
    return ProjectFormSet(request.POST if bound else None,
                          request.FILES if bound else None,
                          instance=post, prefix="projects")
