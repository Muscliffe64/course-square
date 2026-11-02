(function (root) {
  'use strict';
  function appendImages(existing, incoming) {
    const additions = Array.from(incoming);
    let error = '';
    if (existing.length + additions.length > 8) error = '一次最多添加 8 张图片，请移除一些后再试。';
    for (const file of additions) {
      const supported = ['image/jpeg', 'image/png', 'image/webp'].includes(file.type)
        || (!file.type && /\.(jpe?g|png|webp)$/i.test(file.name));
      if (!supported) { error = '仅支持 JPEG、PNG、WebP 图片，本次添加未保存。'; break; }
      if (file.size > 8 * 1024 * 1024) { error = '每张图片不能超过 8 MB，本次添加未保存。'; break; }
    }
    return {files: error ? existing.slice() : existing.concat(additions), error};
  }
  function mount(form) {
    const input = form.querySelector('[data-image-input]');
    const add = form.querySelector('[data-image-add]');
    const previews = form.querySelector('[data-image-previews]');
    const status = form.querySelector('[data-image-status]');
    const cover = form.querySelector('[data-image-cover]');
    const controls = form.querySelector('[data-image-controls]');
    if (!input || !add || !previews || !status || form.dataset.imagePickerMounted) return;
    form.dataset.imagePickerMounted = 'true';
    let files = Array.from(input.files || []);
    let urls = [];
    let depth = 0;
    const help = form.dataset.imageHelp || '拖入图片或粘贴截图，也可以点“添加图片”（最多 8 张，每张 8 MB）。';
    function sync() {
      const data = new DataTransfer();
      files.forEach(file => data.items.add(file));
      input.files = data.files;
      if (cover) cover.value = files.length ? 'new:0' : '';
    }
    function render() {
      urls.forEach(url => URL.revokeObjectURL(url)); urls = [];
      previews.replaceChildren();
      files.forEach((file, index) => {
        const card = document.createElement('div'); card.className = 'image-picker-item';
        const image = document.createElement('img');
        image.src = URL.createObjectURL(file); urls.push(image.src);
        image.alt = file.name;
        const caption = document.createElement('span');
        caption.textContent = index === 0 ? '首页封面 · ' + file.name : file.name;
        const remove = document.createElement('button');
        remove.type = 'button'; remove.textContent = '移除';
        remove.setAttribute('aria-label', '移除图片：' + file.name);
        remove.addEventListener('click', () => {
          files.splice(index, 1); sync(); render();
          const next = previews.querySelectorAll('button')[Math.min(index, files.length - 1)];
          (next || add).focus();
        });
        card.append(image, caption, remove); previews.append(card);
      });
      previews.hidden = files.length === 0;
      status.textContent = files.length ? '已添加 ' + files.length + ' / 8 张图片；发布时与文字一起上传。' : help;
      status.classList.remove('image-picker-error');
    }
    function append(incoming) {
      const result = appendImages(files, incoming);
      if (result.error) {
        sync(); status.textContent = result.error;
        status.classList.add('image-picker-error'); return;
      }
      files = result.files; sync(); render();
    }
    function updateMode() {
      const mode = form.querySelector('input[name="mode"]:checked');
      const disabled = !!mode && mode.value === 'teacher';
      input.disabled = disabled;
      if (cover) cover.disabled = disabled;
      if (controls) controls.hidden = disabled;
      form.classList.remove('image-picker-dragging'); depth = 0;
    }
    add.addEventListener('click', () => { if (!input.disabled) input.click(); });
    input.addEventListener('change', () => append(Array.from(input.files || [])));
    form.addEventListener('dragenter', event => {
      if (!event.dataTransfer || !Array.from(event.dataTransfer.types).includes('Files')) return;
      event.preventDefault(); depth++;
      if (!input.disabled) form.classList.add('image-picker-dragging');
    });
    form.addEventListener('dragover', event => {
      if (!event.dataTransfer || !Array.from(event.dataTransfer.types).includes('Files')) return;
      event.preventDefault(); event.dataTransfer.dropEffect = input.disabled ? 'none' : 'copy';
    });
    form.addEventListener('dragleave', () => {
      depth = Math.max(0, depth - 1);
      if (!depth) form.classList.remove('image-picker-dragging');
    });
    form.addEventListener('drop', event => {
      if (!event.dataTransfer || !event.dataTransfer.files.length) return;
      event.preventDefault(); depth = 0; form.classList.remove('image-picker-dragging');
      if (!input.disabled) append(event.dataTransfer.files);
    });
    const body = form.querySelector('textarea[name="body"]');
    if (body) body.addEventListener('paste', event => {
      if (input.disabled || !event.clipboardData) return;
      const images = Array.from(event.clipboardData.items)
        .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
        .map(item => item.getAsFile()).filter(Boolean);
      if (!images.length) return;
      event.preventDefault(); append(images);
    });
    form.addEventListener('change', event => { if (event.target.name === 'mode') updateMode(); });
    window.addEventListener('pagehide', event => {
      if (!event.persisted) urls.forEach(url => URL.revokeObjectURL(url));
    });
    sync(); render(); updateMode();
  }
  const api = {appendImages, mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else {
    root.ImagePicker = api;
    const start = () => document.querySelectorAll('[data-image-picker]').forEach(mount);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  }
})(typeof window !== 'undefined' ? window : globalThis);
