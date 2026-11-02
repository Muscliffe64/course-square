(() => {
  'use strict';
  const dialog = document.querySelector('[data-composer-dialog]');
  const opener = document.querySelector('[data-composer-open]');
  if (!dialog || !opener || typeof dialog.showModal !== 'function') return;
  const form = dialog.querySelector('[data-composer]');
  const body = form.querySelector('[name=body]');
  const summary = opener.querySelector('[data-composer-summary]');
  function updateSummary() {
    const text = body.value.trim().replace(/\s+/g, ' ');
    const files = Array.from(form.querySelectorAll('input[type=file]')).some(input => !input.disabled && input.files.length);
    summary.textContent = text ? '继续编辑：' + text : files ? '继续编辑：已添加附件' : '分享点什么……';
  }
  function open() {
    if (dialog.open) return;
    dialog.showModal();
    document.documentElement.classList.add('composer-dialog-open');
    opener.setAttribute('aria-expanded', 'true');
    body.focus();
    body.dispatchEvent(new Event('input', {bubbles: true}));
  }
  opener.addEventListener('click', event => { event.preventDefault(); open(); });
  dialog.querySelector('[data-composer-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    document.documentElement.classList.remove('composer-dialog-open');
    opener.setAttribute('aria-expanded', 'false');
    updateSummary();
    opener.focus();
  });
  // Native dialog keeps focus inside, supports Escape, and never resets the form.
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  if (dialog.hasAttribute('data-composer-reopen')) open();
})();
