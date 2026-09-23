# 作品与分享图片画廊与发布者编辑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持一条作品/分享保存多张图片、选择首页封面，并允许作者编辑自己的标题、正文和媒体。

**Architecture:** 新建 `PostImage` 作为 `Post` 的图片画廊记录，保留旧 `Post.image` 并通过 `Post.cover_image` 回退，以保证旧内容与旧图片链接继续可用。表单负责验证多图和封面选择，视图原子化保存图片与内容；模板只使用封面图作为列表预览，详情页按“封面—正文—其余图片—媒体”顺序呈现。

**Tech Stack:** Django、SQLite、Django TestCase、Pillow、现有 HTML/CSS/原生 JavaScript。

## Global Constraints

- 每次最多上传 8 张 JPEG、PNG 或 WebP 图片，每张不超过 8 MB。
- 不支持视频文件上传；只保留视频链接。
- 用户不能在此版本单独删除已上传图片或音频；未提交新文件时保留原文件。
- 编辑权限仅限帖子作者和管理员；媒体文件仍需登录后读取。
- 首页/列表只显示一张选定封面；详情页封面在正文之前，图片不裁切主体。

---

## 文件结构

- 修改 `board/models.py`：增加图片画廊模型、封面回退属性及图片文件名保存。
- 新建 `board/migrations/0006_postimage.py`：创建画廊表并把旧单图初始化为封面。
- 修改 `board/forms.py`：多文件图片字段、封面选择验证和媒体保留语义。
- 修改 `board/views.py` 与 `board/urls.py`：创建/编辑保存、图片画廊读取、作者权限。
- 修改 `board/feed.py`：预取画廊图片，避免首页逐卡片查询。
- 修改 `templates/board/post_form.html`：多图预览与封面选择；编辑标题和按钮文案。
- 修改 `templates/board/post_detail.html`、`templates/board/includes/post_card.html`：新的图片展示顺序和编辑入口。
- 修改 `static/board/app.css`：完整封面、缩略图画廊和封面选择控件。
- 修改 `board/admin.py`：让管理员可查看画廊记录。
- 新建/修改 `board/test_gallery.py`：覆盖图片画廊、封面、编辑与展示的行为。

### Task 1: 图片画廊数据模型与旧内容兼容

**Files:**
- Modify: `board/models.py`
- Create: `board/migrations/0006_postimage.py`
- Create: `board/test_gallery.py`

**Interfaces:**
- Produces `PostImage(post, image, original_filename, is_cover)`。
- Produces `Post.cover_image`（`PostImage | None`）和 `Post.cover_image_file`（当前封面上传文件或旧 `Post.image`）。

- [ ] **Step 1: 写出失败测试**

```python
class PostGalleryModelTests(TestCase):
    def test_selected_gallery_image_is_the_cover(self):
        post = Post.objects.create(author=self.user, title="多图", body="正文", kind="showcase")
        first = PostImage.objects.create(post=post, image=self.image_upload("第一张.png"))
        cover = PostImage.objects.create(post=post, image=self.image_upload("封面.png"), is_cover=True)
        post.refresh_from_db()
        self.assertEqual(post.cover_image.pk, cover.pk)
        self.assertEqual(post.cover_image_file.name, cover.image.name)

    def test_legacy_post_image_is_used_when_gallery_is_empty(self):
        post = Post.objects.create(author=self.user, title="旧图", body="正文", kind="showcase", image=self.image_upload())
        self.assertIsNone(post.cover_image)
        self.assertEqual(post.cover_image_file.name, post.image.name)
```

- [ ] **Step 2: 运行模型测试，确认因 `PostImage` 尚不存在而失败**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryModelTests -v 2`

Expected: `ImportError` 或 `NameError`，指出 `PostImage` 未定义。

- [ ] **Step 3: 实现最小模型与迁移**

```python
class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="gallery_images")
    image = models.ImageField("图片", upload_to=random_upload, validators=[validate_image])
    original_filename = models.CharField("图片原文件名", max_length=255, editable=False)
    is_cover = models.BooleanField("首页封面", default=False)
    created_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["post"], condition=models.Q(is_cover=True), name="one_cover_per_post"
        )]

    def save(self, *args, **kwargs):
        if self.image and not self.image._committed:
            self.original_filename = Path(self.image.name).name
        super().save(*args, **kwargs)
```

Add `Post.cover_image` / `cover_image_file` properties that prefer the one `gallery_images` record marked `is_cover`, then fall back to `Post.image`. Generate the migration with `makemigrations`; in its `RunPython`, create a `PostImage` for every existing row with `Post.image`, copying the stored name and `image_original_filename`, and set `is_cover=True`.

- [ ] **Step 4: 运行模型与迁移测试，确认通过**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryModelTests -v 2`

Expected: `OK`。

- [ ] **Step 5: 提交模型工作**

```bash
git add board/models.py board/migrations/0006_postimage.py board/test_gallery.py
git commit -m "feat: add post image gallery"
```

### Task 2: 多图发布表单与封面选择

**Files:**
- Modify: `board/forms.py`
- Modify: `board/views.py`
- Modify: `templates/board/post_form.html`
- Modify: `board/test_gallery.py`

**Interfaces:**
- Produces `PostForm.images`，其值为通过现有 `validate_image` 验证的上传列表。
- Produces `PostForm.save_gallery(post)`，保存上传图片并按 `cover_choice` 设定唯一封面。
- Consumes `cover_choice`，格式为 `new:<0-based index>` 或 `existing:<PostImage.pk>`。

- [ ] **Step 1: 写出失败测试**

```python
def test_publish_multiple_images_uses_selected_new_cover(self):
    response = self.client.post(reverse("board:post_create"), {
        "title": "三张图", "body": "正文", "kind": "showcase",
        "images": [self.image_upload("一.png"), self.image_upload("二.png")],
        "cover_choice": "new:1",
    })
    post = Post.objects.get(title="三张图")
    self.assertRedirects(response, reverse("board:post_detail", args=[post.pk]))
    self.assertEqual(post.gallery_images.count(), 2)
    self.assertEqual(post.cover_image.original_filename, "二.png")

def test_publish_rejects_more_than_eight_images(self):
    response = self.client.post(reverse("board:post_create"), {
        "title": "太多图", "body": "正文", "kind": "showcase",
        "images": [self.image_upload(f"{i}.png") for i in range(9)],
    })
    self.assertEqual(response.status_code, 200)
    self.assertIn("images", response.context["form"].errors)
```

- [ ] **Step 2: 运行表单测试，确认因字段与保存方法不存在而失败**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryPublishTests -v 2`

Expected: `FAIL`，帖子没有画廊图片或表单不认识 `images`。

- [ ] **Step 3: 最小实现多文件字段和保存方法**

```python
class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleImageField(forms.ImageField):
    widget = MultipleImageInput
    def clean(self, data, initial=None):
        values = [] if not data else data
        return [super(MultipleImageField, self).clean(item, initial) for item in values]
```

In `PostForm`, replace the public `image` input with `images` and hidden `cover_choice`; `clean_images` rejects more than 8 images, and `clean_cover_choice` accepts only an existing image of `self.instance` or one valid new index. `save_gallery` first creates new `PostImage` records, then clears any old cover and sets the selected record (first new image when no selection exists). In `post_create`, call `form.save_gallery(post)` inside `transaction.atomic()` after the post has a primary key.

- [ ] **Step 4: 增加首图默认封面与无图兼容测试，运行通过**

```python
def test_publish_defaults_to_first_image_as_cover(self):
    response = self.client.post(reverse("board:post_create"), self.publish_data_with_two_images())
    post = Post.objects.get(title="两张图")
    self.assertRedirects(response, reverse("board:post_detail", args=[post.pk]))
    self.assertEqual(post.cover_image.original_filename, "一.png")
```

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryPublishTests -v 2`

Expected: `OK`。

- [ ] **Step 5: 提交发布表单工作**

```bash
git add board/forms.py board/views.py templates/board/post_form.html board/test_gallery.py
git commit -m "feat: publish multi-image posts"
```

### Task 3: 作者编辑自己的帖子及媒体保留

**Files:**
- Modify: `board/views.py`
- Modify: `board/urls.py`
- Modify: `templates/board/post_form.html`
- Modify: `templates/board/post_detail.html`
- Modify: `board/test_gallery.py`

**Interfaces:**
- Produces `board:post_edit` at `posts/<pk>/edit/`。
- Reuses `PostForm(instance=post)` and `_can_delete(user, post)` permission predicate.

- [ ] **Step 1: 写出失败的权限与保存测试**

```python
def test_author_can_edit_title_body_audio_and_cover(self):
    post, old_cover, other = self.create_gallery_post()
    response = self.client.post(reverse("board:post_edit", args=[post.pk]), {
        "title": "更新标题", "body": "更新正文", "kind": "showcase",
        "cover_choice": f"existing:{other.pk}",
        "audio": SimpleUploadedFile("新版.mp3", b"ID3new"),
    })
    post.refresh_from_db()
    self.assertRedirects(response, reverse("board:post_detail", args=[post.pk]))
    self.assertEqual(post.title, "更新标题")
    self.assertEqual(post.cover_image.pk, other.pk)
    self.assertEqual(post.audio_original_filename, "新版.mp3")

def test_non_author_cannot_edit_post(self):
    post, _, _ = self.create_gallery_post()
    self.client.force_login(self.other_user)
    self.assertEqual(self.client.get(reverse("board:post_edit", args=[post.pk])).status_code, 403)
```

- [ ] **Step 2: 运行编辑测试，确认 URL/视图尚不存在而失败**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostEditTests -v 2`

Expected: `NoReverseMatch` 或 `404`，指向缺少 `post_edit`。

- [ ] **Step 3: 实现编辑视图和入口**

```python
@login_required
def post_edit(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if not _can_delete(request.user, post):
        raise PermissionDenied
    form = PostForm(request.POST or None, request.FILES or None, instance=post)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            post = form.save()
            form.save_gallery(post)
        messages.success(request, "已更新。")
        return redirect("board:post_detail", pk=post.pk)
    return render(request, "board/post_form.html", common_context() | {"form": form, "post": post})
```

Add the route and show “编辑内容” in the detail action area for the author or administrator. Make form title, breadcrumb and submit label conditional on whether `post` is present. Keep existing media when no replacement file is submitted; URL fields keep normal editable values so a user may deliberately clear a link.

- [ ] **Step 4: 写并运行媒体保留回归测试**

```python
def test_edit_without_new_files_keeps_existing_gallery_and_audio(self):
    post, cover, _ = self.create_gallery_post(with_audio=True)
    self.client.post(reverse("board:post_edit", args=[post.pk]), {
        "title": "只改文字", "body": "新正文", "kind": "showcase", "cover_choice": f"existing:{cover.pk}",
    })
    post.refresh_from_db()
    self.assertEqual(post.gallery_images.count(), 2)
    self.assertEqual(post.cover_image.pk, cover.pk)
    self.assertEqual(post.audio_original_filename, "原音频.mp3")
```

Run: `./.venv/bin/python manage.py test board.test_gallery.PostEditTests -v 2`

Expected: `OK`。

- [ ] **Step 5: 提交编辑工作**

```bash
git add board/views.py board/urls.py templates/board/post_form.html templates/board/post_detail.html board/test_gallery.py
git commit -m "feat: let authors edit posts"
```

### Task 4: 列表/详情展示与安全图片读取

**Files:**
- Modify: `board/views.py`
- Modify: `board/urls.py`
- Modify: `board/feed.py`
- Modify: `templates/board/includes/post_card.html`
- Modify: `templates/board/post_detail.html`
- Modify: `static/board/app.css`
- Modify: `board/test_gallery.py`

**Interfaces:**
- `board:post_image` returns the selected cover or legacy image.
- `board:post_gallery_image(post_pk, image_pk)` returns one authenticated gallery image.

- [ ] **Step 1: 写出失败的展示与访问控制测试**

```python
def test_card_uses_only_selected_cover_and_detail_places_cover_before_body(self):
    post, cover, other = self.create_gallery_post()
    card = self.client.get(reverse("board:home")).content.decode()
    detail = self.client.get(reverse("board:post_detail", args=[post.pk])).content.decode()
    self.assertIn(reverse("board:post_image", args=[post.pk]), card)
    self.assertNotIn(reverse("board:post_gallery_image", args=[post.pk, other.pk]), card)
    self.assertLess(detail.index(reverse("board:post_image", args=[post.pk])), detail.index("正文"))

def test_gallery_image_requires_login_and_belongs_to_post(self):
    post, _, image = self.create_gallery_post()
    url = reverse("board:post_gallery_image", args=[post.pk, image.pk])
    self.client.logout()
    self.assertEqual(self.client.get(url).status_code, 302)
    self.client.force_login(self.user)
    self.assertEqual(self.client.get(url).status_code, 200)
```

- [ ] **Step 2: 运行展示测试，确认因画廊图片 URL 与模板尚不存在而失败**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryDisplayTests -v 2`

Expected: `NoReverseMatch` 或 HTML 顺序断言失败。

- [ ] **Step 3: 实现展示和受保护媒体 URL**

```python
@login_required
def post_gallery_image(request, post_pk, image_pk):
    image = get_object_or_404(PostImage, pk=image_pk, post_id=post_pk)
    return _post_media_response(image.image, image.original_filename, IMAGE_CONTENT_TYPES)
```

Make `post_image` pass `post.cover_image_file` and its corresponding filename to `_post_media_response`. Add `prefetch_related("gallery_images")` to the feed query and the detail query. In the card put the cover image before the text excerpt, rendered with `object-fit: contain`; in the detail template render the cover immediately before `.post-body`, then render non-cover images in a responsive gallery after the body. Use only safe `{% url %}` image sources and authenticated views.

- [ ] **Step 4: 运行展示测试和现有媒体回归测试**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryDisplayTests board.test_media -v 2`

Expected: `OK`。

- [ ] **Step 5: 提交展示工作**

```bash
git add board/views.py board/urls.py board/feed.py templates/board/includes/post_card.html templates/board/post_detail.html static/board/app.css board/test_gallery.py
git commit -m "feat: show selected post cover and gallery"
```

### Task 5: 管理入口、全量验证和发布检查

**Files:**
- Modify: `board/admin.py`
- Modify: `board/test_gallery.py`

**Interfaces:**
- Produces admin registration or inline for `PostImage` without changing public authorization.

- [ ] **Step 1: 写出管理员可编辑而非作者不可编辑的回归测试**

```python
def test_staff_can_edit_another_users_post(self):
    post, _, _ = self.create_gallery_post()
    self.client.force_login(self.staff)
    response = self.client.post(reverse("board:post_edit", args=[post.pk]), {
        "title": "管理员更新", "body": "正文", "kind": "showcase",
    })
    post.refresh_from_db()
    self.assertRedirects(response, reverse("board:post_detail", args=[post.pk]))
    self.assertEqual(post.title, "管理员更新")
```

- [ ] **Step 2: 运行测试，确认通过或补齐遗漏权限逻辑**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostEditTests -v 2`

Expected: `OK`。

- [ ] **Step 3: 增加 `PostImage` 的后台可见入口**

```python
class PostImageInline(admin.TabularInline):
    model = PostImage
    extra = 0

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    inlines = [PostImageInline]
```

- [ ] **Step 4: 运行迁移检查、全量测试和静态收集检查**

Run: `./.venv/bin/python manage.py makemigrations --check && ./.venv/bin/python manage.py test board -v 1 && ./.venv/bin/python manage.py collectstatic --noinput --dry-run`

Expected: 无未生成迁移、全部测试 `OK`、静态文件检查成功。

- [ ] **Step 5: 提交验证后的代码**

```bash
git add board/admin.py board/test_gallery.py
git commit -m "feat: manage post galleries"
```
