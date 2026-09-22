/** Non-blocking status messages, optionally with one action (e.g. Undo). base.html provides #toast. */

let hideTimer;

function hide() {
  const toast = document.querySelector('#toast');
  toast?.classList.remove('visible', 'has-action');
}

/**
 * showToast('Saved')
 * showToast('Shift removed', { action: { label: 'Undo', onClick: () => restore() }, duration: 6000 })
 */
export function showToast(message, { type = 'info', duration = 3200, action = null } = {}) {
  const toast = document.querySelector('#toast');
  if (!toast) return;
  clearTimeout(hideTimer);
  toast.textContent = '';
  const text = document.createElement('span');
  text.className = 'toast-text';
  text.textContent = message;
  toast.appendChild(text);
  if (action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'toast-action';
    button.textContent = action.label;
    button.addEventListener('click', () => { hide(); action.onClick(); });
    toast.appendChild(button);
  }
  toast.classList.toggle('error', type === 'error');
  toast.classList.toggle('has-action', Boolean(action));
  toast.classList.add('visible');
  hideTimer = window.setTimeout(hide, duration);
}

export function showError(message) {
  showToast(message, { type: 'error', duration: 4500 });
}
