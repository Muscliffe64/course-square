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
