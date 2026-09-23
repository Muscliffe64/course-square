# 首页帖子展开与详情入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make homepage post cards compact while allowing readers to expand long text and enter a post through clear detail links.

**Architecture:** Server-rendered cards provide both a shortened excerpt and a hidden full-text region. A small delegated JavaScript handler toggles the region in-place, with no new endpoint or database state. CSS limits the homepage preview height while preserving `object-fit: contain` so the whole image stays visible.

**Tech Stack:** Django templates/tests, vanilla JavaScript, CSS.

## Global Constraints

- Homepage cover images must be complete, never cropped, and use a visibly smaller fixed preview height.
- Only text expands in place; audio remains playable in the card and video remains a detail-page experience.
- Do not turn the whole post card into a link because it contains independent controls.
- Preserve title and image detail links, and add a visible “查看详情” link.
- The interaction must use a real button and synchronized ARIA state.

---

### Task 1: Render expandable post bodies and a clear detail entry

**Files:**
- Modify: `templates/board/includes/post_card.html`
- Test: `board/test_gallery.py`

**Interfaces:**
- Consumes: `post.pk`, `post.body`, and `board:post_detail` from the existing card context.
- Produces: `.post-full-body`, `[data-post-expand]`, and `.post-detail-link` elements.

- [ ] **Step 1: Write the failing template test**

```python
def test_home_card_has_expandable_full_body_and_detail_link(self):
    post, _, _ = self.create_gallery_post()
    post.body = "首段" + "长正文" * 100
    post.save(update_fields=["body"])
    response = self.client.get(reverse("board:home"))
    self.assertContains(response, "data-post-expand")
    self.assertContains(response, f'id="post-full-{post.pk}"')
    self.assertContains(response, "展开全文")
    self.assertContains(response, "查看详情")
    self.assertContains(response, reverse("board:post_detail", args=[post.pk]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryDisplayTests.test_home_card_has_expandable_full_body_and_detail_link -v 1`

Expected: FAIL because the card has none of the new expand/detail markup.

- [ ] **Step 3: Write minimal implementation**

```django
<p class="post-excerpt">{{ post.body|truncatechars:180 }}</p>
<div id="post-full-{{ post.pk }}" class="post-full-body" hidden>{{ post.body|linebreaksbr }}</div>
<button type="button" class="post-expand-toggle" data-post-expand aria-expanded="false" aria-controls="post-full-{{ post.pk }}"><span data-expand-label>展开全文</span><span data-expand-arrow aria-hidden="true">↓</span></button>
<a class="post-detail-link" href="{% url 'board:post_detail' post.pk %}">查看详情 <span aria-hidden="true">→</span></a>
```

Render the expand controls only when `post.body|length > 180`, using a template-compatible condition; do not add a new view endpoint.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryDisplayTests.test_home_card_has_expandable_full_body_and_detail_link -v 1`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/board/includes/post_card.html board/test_gallery.py
git commit -m "feat: add expandable homepage post bodies"
```

### Task 2: Add accessible in-place behavior and compact preview styling

**Files:**
- Modify: `static/board/app.js`
- Modify: `static/board/app.css`
- Test: `board/test_gallery.py`

**Interfaces:**
- Consumes: Task 1's `[data-post-expand]`, `aria-controls`, `.post-full-body`, and detail-link classes.
- Produces: a button that toggles target visibility, `aria-expanded`, its label, and arrow without navigation.

- [ ] **Step 1: Write the failing static-asset test**

```python
def test_home_card_assets_define_expand_and_compact_cover_behavior(self):
    app_js = Path(settings.BASE_DIR / "static/board/app.js").read_text()
    app_css = Path(settings.BASE_DIR / "static/board/app.css").read_text()
    self.assertIn("data-post-expand", app_js)
    self.assertIn("aria-expanded", app_js)
    self.assertIn("post-full-body", app_css)
    self.assertIn(".post-image-preview img", app_css)
    self.assertIn("height:220px", app_css)
```

Add the required `Path` and `settings` imports to the test module.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryDisplayTests.test_home_card_assets_define_expand_and_compact_cover_behavior -v 1`

Expected: FAIL because no post-expansion behavior or compact cover rule exists.

- [ ] **Step 3: Write minimal implementation**

```javascript
document.addEventListener('click', (event) => {
  const toggle = event.target.closest('[data-post-expand]');
  if (!toggle) return;
  const fullBody = document.getElementById(toggle.getAttribute('aria-controls'));
  if (!fullBody) return;
  const expanded = toggle.getAttribute('aria-expanded') === 'true';
  fullBody.hidden = expanded;
  toggle.setAttribute('aria-expanded', String(!expanded));
  toggle.querySelector('[data-expand-label]').textContent = expanded ? '展开全文' : '收起全文';
  toggle.querySelector('[data-expand-arrow]').textContent = expanded ? '↓' : '↑';
});
```

```css
.post-image-preview img{width:100%;height:220px;max-height:none;object-fit:contain;background:#f6f7f2}
.post-full-body{margin:0 0 12px;line-height:1.85}
.post-expand-toggle,.post-detail-link{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:#5b7050;background:transparent;border:0;padding:0;margin:0 0 16px}
.post-detail-link{margin-left:14px}
@media(max-width:700px){.post-image-preview img{height:165px}.post-detail-link{margin-left:11px}}
```

Retain the existing card media controls and their layout.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python manage.py test board.test_gallery.PostGalleryDisplayTests.test_home_card_assets_define_expand_and_compact_cover_behavior -v 1`

Expected: PASS.

- [ ] **Step 5: Run regression tests**

Run: `./.venv/bin/python manage.py test board.test_gallery -v 1`

Expected: PASS with no failures.

- [ ] **Step 6: Commit**

```bash
git add static/board/app.js static/board/app.css board/test_gallery.py
git commit -m "feat: expand homepage posts in place"
```

### Task 3: Verify the full application and deploy

**Files:**
- Modify: none
- Test: full Django test suite

**Interfaces:**
- Consumes: completed Tasks 1 and 2.
- Produces: verified release archive and live deployment result.

- [ ] **Step 1: Run the complete test suite**

Run: `./.venv/bin/python manage.py test -v 1`

Expected: PASS with zero failures.

- [ ] **Step 2: Inspect the finished source changes**

Run: `git diff HEAD~2..HEAD -- templates/board/includes/post_card.html static/board/app.js static/board/app.css board/test_gallery.py`

Expected: only the compact preview, in-place expansion, detail link, and their regression coverage.

- [ ] **Step 3: Deploy the tested source archive**

Run: create an archive containing the changed application files, upload it through the authenticated server workspace, unpack it into a copy of `/opt/course-square/current`, and run `deploy/install.sh 123.57.56.38` in the background.

Expected: deployment logs report no migration error and `systemctl is-active course-square` returns `active`.

- [ ] **Step 4: Verify the public health endpoint**

Run: `curl -fsS https://123.57.56.38/healthz/`

Expected: `ok`.
