(() => {
  'use strict';
  document.querySelectorAll('[data-markdown-form]').forEach(form => {
    const picker = form.querySelector('[data-markdown-picker]');
    if (!picker) return;
    const input = picker.querySelector('[data-markdown-input]');
    const status = picker.querySelector('[data-markdown-status]');
    const remove = picker.querySelector('[data-markdown-remove]');
    const clear = picker.querySelector('[data-markdown-clear]');
    const body = form.querySelector('[name=body]');
    const title = form.querySelector('[name=title]');
    const quick = form.hasAttribute('data-composer');
    if (!input) return;
    const existing = picker.dataset.markdownExisting === 'true';
    function sync() {
      const mode = form.querySelector('[name=mode]:checked');
      const privateMode = mode && mode.value === 'teacher';
      input.disabled = !!privateMode;
      const file = input.files[0];
      const hasFile = !privateMode && (!!file || (existing && !(clear && clear.checked)));
      if (body) body.required = !hasFile;
      if (title) title.required = !hasFile;
      if (remove) remove.hidden = !file;
      return hasFile;
    }
    input.addEventListener('change', () => {
      const file = input.files[0];
      status.classList.remove('markdown-error');
      if (file && (!/\.(md|markdown)$/i.test(file.name) || file.size > 2 * 1024 * 1024 || !file.size)) {
        input.value = '';
        status.textContent = '请选择非空的 .md 或 .markdown 文件，最大 2 MB。';
        status.classList.add('markdown-error');
      } else if (file) {
        if (clear) clear.checked = false;
        const share = form.querySelector('[name=mode][value=showcase]');
        if (quick && share) { share.checked = true; share.dispatchEvent(new Event('change', {bubbles:true})); }
        status.textContent = '已选择 ' + file.name + '；发布后支持在线阅读与下载，附言选填。';
      } else {
        status.textContent = '每帖一份，最大 2 MB；可直接分享文件，附言选填。';
      }
      sync();
    });
    if (remove) remove.addEventListener('click', () => { input.value = ''; input.dispatchEvent(new Event('change', {bubbles:true})); input.focus(); });
    form.addEventListener('change', event => { if (event.target.name === 'mode' || event.target === clear) sync(); });
    window.addEventListener('pageshow', sync);
    sync();
  });
})();
