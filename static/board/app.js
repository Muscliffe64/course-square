document.addEventListener('click', (event) => {
  const toggle = event.target.closest('[data-toggle-password]');
  if (!toggle) return;
  const input = document.getElementById(toggle.dataset.togglePassword);
  if (!input) return;
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  toggle.textContent = show ? '隐藏' : '显示';
  toggle.setAttribute('aria-label', show ? '隐藏密码' : '显示密码');
});
document.addEventListener('submit', (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});
document.addEventListener('click', (event) => {
  const toggle = event.target.closest('[data-post-expand]');
  if (!toggle) return;
  const fullBody = document.getElementById(toggle.getAttribute('aria-controls'));
  if (!fullBody) return;
  const expanded = toggle.getAttribute('aria-expanded') === 'true';
  const excerpt = toggle.closest('.post-card').querySelector('[data-post-excerpt]');
  fullBody.hidden = expanded;
  if (excerpt) excerpt.hidden = !expanded;
  toggle.setAttribute('aria-expanded', String(!expanded));
  toggle.querySelector('[data-expand-label]').textContent = expanded ? '展开全文' : '收起全文';
  toggle.querySelector('[data-expand-arrow]').textContent = expanded ? '↓' : '↑';
});
// 首页一行发帖：输入框随内容长高；勾「只给老师看」时收起公开选项；提交后禁用按钮防止双击。
// border-box 下高度要加上边框，否则永远差 2px，Mac 上会冒出滚动条。
const autosize = (area) => {
  area.style.height = 'auto';
  const border = area.offsetHeight - area.clientHeight;
  const max = parseFloat(getComputedStyle(area).maxHeight) || Infinity;
  const wanted = area.scrollHeight + border;
  area.style.height = `${Math.min(wanted, max)}px`;
  area.style.overflowY = wanted > max ? 'auto' : 'hidden';
};
document.addEventListener('input', (event) => {
  if (event.target.matches('[data-autosize]')) autosize(event.target);
});
// 发帖框三个去处：想听的主题 / 作品与分享 / 问老师。切换时换标题、示例文字和可用选项。
const syncComposer = (form) => {
  const checked = form.querySelector('input[name=mode]:checked');
  const mode = checked ? checked.value : 'topic';
  form.classList.toggle('is-private', mode === 'teacher');
  form.querySelectorAll('[data-mode]').forEach((el) => { el.hidden = !el.dataset.mode.split(' ').includes(mode); });
  const area = form.querySelector('textarea');
  const key = `placeholder${mode.charAt(0).toUpperCase()}${mode.slice(1)}`;
  if (area && area.dataset[key]) area.placeholder = area.dataset[key];
  const full = form.querySelector('.composer-full');
  if (full) full.href = full.href.replace(/kind=\w+/, `kind=${mode === 'showcase' ? 'showcase' : 'topic'}`);
  const submit = form.querySelector('[data-composer-submit]');
  if (submit && !submit.disabled) submit.textContent = mode === 'teacher' ? '交给老师' : '发布';
};
document.addEventListener('change', (event) => {
  const form = event.target.closest('[data-composer]');
  if (form && event.target.matches('input[name=mode]')) syncComposer(form);
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && event.target.matches('[data-composer] textarea')) {
    event.preventDefault();
    event.target.form.requestSubmit();
  }
});
document.addEventListener('submit', (event) => {
  if (event.defaultPrevented || !event.target.matches('[data-composer]')) return;
  const submit = event.target.querySelector('[data-composer-submit]');
  if (submit) { submit.disabled = true; submit.textContent = '发送中…'; }
});
document.querySelectorAll('[data-composer]').forEach((form) => {
  syncComposer(form);
  form.querySelectorAll('[data-autosize]').forEach(autosize);
});
window.addEventListener('pageshow', (event) => {
  if (event.persisted) document.querySelectorAll('[data-composer]').forEach((form) => {
    const submit = form.querySelector('[data-composer-submit]');
    if (submit) submit.disabled = false;
    syncComposer(form);
  });
});
