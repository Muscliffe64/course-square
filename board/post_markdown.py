"""Validated private Markdown attachments for ordinary posts."""
import hashlib
import uuid
from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from markdown_it import MarkdownIt

MAX_POST_MARKDOWN_BYTES = 2 * 1024 * 1024


def markdown_upload(instance, filename):
    return f'post-markdown/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


def validate_post_markdown(upload):
    if Path(upload.name).suffix.lower() not in {'.md', '.markdown'}:
        raise ValidationError('仅支持 .md 或 .markdown 文件。')
    if upload.size > MAX_POST_MARKDOWN_BYTES:
        raise ValidationError('Markdown 文件不能超过 2 MB。')
    try:
        upload.seek(0)
        raw = upload.read(MAX_POST_MARKDOWN_BYTES + 1)
        if len(raw) > MAX_POST_MARKDOWN_BYTES:
            raise ValidationError('Markdown 文件不能超过 2 MB。')
        text = raw.decode('utf-8-sig')
        if '\x00' in text:
            raise ValidationError('请上传文本格式的 Markdown 文件。')
        if not text.strip():
            raise ValidationError('Markdown 文件内容不能为空。')
    except UnicodeDecodeError as exc:
        raise ValidationError('请将 Markdown 文件保存为 UTF-8 编码后上传。') from exc
    finally:
        upload.seek(0)


def markdown_digest(upload):
    if not upload:
        return ''
    try:
        upload.seek(0)
        return hashlib.sha256(upload.read(MAX_POST_MARKDOWN_BYTES + 1)).hexdigest()
    finally:
        upload.seek(0)


def _attachment(pk):
    from .models import Post
    post = get_object_or_404(Post.objects.select_related('author'), pk=pk)
    if not post.markdown_file:
        raise Http404
    try:
        return post, post.markdown_file.open('rb')
    except FileNotFoundError as exc:
        raise Http404 from exc


@login_required
def read(request, pk):
    post, upload = _attachment(pk)
    with upload:
        raw = upload.read(MAX_POST_MARKDOWN_BYTES + 1)
    if len(raw) > MAX_POST_MARKDOWN_BYTES:
        raise Http404
    html = MarkdownIt('gfm-like', {'html': False, 'linkify': False, 'breaks': True}).render(raw.decode('utf-8-sig', errors='replace'))
    return render(request, 'board/post_markdown_read.html', {'post': post, 'content_html': html})


@login_required
def download(request, pk):
    post, upload = _attachment(pk)
    response = FileResponse(upload, as_attachment=True, filename=post.markdown_filename, content_type='text/markdown; charset=utf-8')
    response['X-Content-Type-Options'] = 'nosniff'
    return response
