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
const autosize = (area) => { area.style.height = 'auto'; area.style.height = `${area.scrollHeight}px`; };
document.addEventListener('input', (event) => {
  if (event.target.matches('[data-autosize]')) autosize(event.target);
});
const syncComposer = (form) => {
  const toTeacher = form.querySelector('[data-to-teacher]');
  const privateMode = Boolean(toTeacher && toTeacher.checked);
  form.classList.toggle('is-private', privateMode);
  form.querySelectorAll('[data-public-only] input').forEach((input) => { input.disabled = privateMode; });
  const hint = form.querySelector('[data-teacher-hint]');
  if (hint) hint.hidden = !privateMode;
  const submit = form.querySelector('[data-composer-submit]');
  if (submit) submit.textContent = privateMode ? '交给老师' : '发布';
};
document.addEventListener('change', (event) => {
  const form = event.target.closest('[data-composer]');
  if (form && event.target.matches('[data-to-teacher]')) syncComposer(form);
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
