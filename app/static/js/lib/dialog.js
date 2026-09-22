/** Confirmation dialog built on <dialog>; base.html provides #confirm-dialog. Resolves true when confirmed. */

export function confirmDialog({ title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false }) {
  const dialog = document.querySelector('#confirm-dialog');
  if (!dialog?.showModal) return Promise.resolve(window.confirm(`${title}\n\n${message}`));

  dialog.querySelector('[data-title]').textContent = title;
  dialog.querySelector('[data-message]').textContent = message;
  const confirmButton = dialog.querySelector('[data-confirm]');
  const cancelButton = dialog.querySelector('[data-cancel]');
  confirmButton.textContent = confirmLabel;
  cancelButton.textContent = cancelLabel;
  confirmButton.classList.toggle('button-danger', danger);
  confirmButton.classList.toggle('button-primary', !danger);

  return new Promise(resolve => {
    const finish = result => {
      dialog.close();
      confirmButton.removeEventListener('click', onConfirm);
      cancelButton.removeEventListener('click', onCancel);
      dialog.removeEventListener('cancel', onCancel);
      dialog.removeEventListener('click', onBackdrop);
      resolve(result);
    };
    const onConfirm = () => finish(true);
    const onCancel = event => { event.preventDefault(); finish(false); };
    const onBackdrop = event => { if (event.target === dialog) finish(false); };
    confirmButton.addEventListener('click', onConfirm);
    cancelButton.addEventListener('click', onCancel);
    dialog.addEventListener('cancel', onCancel);
    dialog.addEventListener('click', onBackdrop);
    dialog.showModal();
    cancelButton.focus();
  });
}
