/** Non-blocking status messages. base.html provides the #toast element. */

let hideTimer;

export function showToast(message, { type = 'info', duration = 3200 } = {}) {
  const toast = document.querySelector('#toast');
  if (!toast) return;
  clearTimeout(hideTimer);
  toast.textContent = message;
  toast.classList.toggle('error', type === 'error');
  toast.classList.add('visible');
  hideTimer = window.setTimeout(() => toast.classList.remove('visible'), duration);
}

export function showError(message) {
  showToast(message, { type: 'error', duration: 4500 });
}
