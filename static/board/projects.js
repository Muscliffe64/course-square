function validateProjectUploads(inputs) {
  let totalBytes = 0; let projectMedia = false; let error = '';
  inputs.forEach(input => {
    for (const file of input.files || []) {
      totalBytes += file.size;
      if (/projects-\d+-(video|poster)$/.test(input.name)) projectMedia = true;
      const max = Number(input.dataset.maxBytes || (input.name === 'audio' ? 25 : 8) * 1024 * 1024);
      if (file.size > max) error = `${file.name} 超过文件大小限制。`;
    }
  });
  if (projectMedia && totalBytes > 64 * 1024 * 1024) error = '本次上传的文件合计不能超过 64 MB。';
  return error;
}
if (typeof module !== 'undefined') module.exports = {validateProjectUploads};
(() => {
  document.querySelectorAll('.project-video').forEach(video => {
    video.addEventListener('play', () => document.querySelectorAll('.project-video').forEach(other => { if (other !== video) other.pause(); }));
    video.addEventListener('error', () => { const error = video.closest('.project-section').querySelector('.video-error'); if (error) error.hidden = false; });
  });
  const editor = document.getElementById('project-editor');
  if (!editor) return;
  const total = document.getElementById('id_projects-TOTAL_FORMS');
  const add = document.getElementById('project-add');
  const rows = document.getElementById('project-rows');
  const activeCount = () => Array.from(rows.querySelectorAll('.project-form-row')).filter(row => !row.querySelector('input[name$="-DELETE"]').checked).length;
  const refresh = () => { add.disabled = activeCount() >= 10; };
  rows.addEventListener('change', refresh);
  add.addEventListener('click', () => {
    if (activeCount() >= 10) return;
    const index = Number(total.value);
    const template = document.getElementById('project-empty-form');
    // Django escapes field values; replace only its numeric field-name placeholder.
    const fragment = template.content.cloneNode(true);
    fragment.querySelectorAll('*').forEach(element => Array.from(element.attributes).forEach(attr => {
      if (attr.value.includes('__prefix__')) element.setAttribute(attr.name, attr.value.replaceAll('__prefix__', String(index)));
    }));
    fragment.querySelector('input[name$="-position"]').value = activeCount() + 1;
    rows.append(fragment); total.value = index + 1; refresh();
  });
  editor.closest('form').addEventListener('submit', event => {
    const error = validateProjectUploads(editor.closest('form').querySelectorAll('input[type=file]'));
    const message = document.getElementById('project-upload-error'); message.textContent = error; message.hidden = !error;
    if (error) { event.preventDefault(); message.scrollIntoView({block: 'center'}); }
  });
  refresh();
})();
