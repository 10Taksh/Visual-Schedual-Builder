import { api } from './lib/api.js';
import { $, $$, DAYS, META, escapeHtml, plural } from './lib/dom.js';
import { availabilityText } from './lib/time.js';
import { showError, showToast } from './lib/toast.js';

const form = $('#employee-form');
const list = $('#employee-list');
const palette = META.palette || [];
let employees = [];

// --- employee form -----------------------------------------------------------

function unusedColor() {
  const used = new Set(employees.map(employee => employee.color.toUpperCase()));
  return palette.find(color => !used.has(color)) || palette[employees.length % palette.length] || '#E07A5F';
}

function resetForm() {
  form.reset();
  $('#employee-id').value = '';
  $('#form-title').textContent = 'Add employee';
  $('#availability').value = 'Open';
  $('#color').value = unusedColor();
  $$('#positions input').forEach(input => { input.checked = false; });
  $$('.employee-card.editing').forEach(card => card.classList.remove('editing'));
}

function editEmployee(employee) {
  $('#employee-id').value = employee.id;
  $('#form-title').textContent = 'Edit employee';
  $('#name').value = employee.name;
  $('#employment-type').value = employee.employment_type;
  $('#availability').value = typeof employee.availability === 'string' ? employee.availability : JSON.stringify(employee.availability);
  $('#color').value = employee.color;
  $$('#positions input').forEach(input => { input.checked = employee.positions.includes(input.value); });
  $$('.employee-card').forEach(card => card.classList.toggle('editing', Number(card.dataset.id) === employee.id));
  window.scrollTo({ top: 0, behavior: 'smooth' });
  $('#name').focus();
}

function readForm() {
  return {
    name: $('#name').value,
    employment_type: $('#employment-type').value,
    positions: $$('#positions input:checked').map(input => input.value),
    availability: $('#availability').value,
    color: $('#color').value,
  };
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const id = $('#employee-id').value;
  const payload = readForm();
  const submit = body => (id ? api.put(`/api/employees/${id}`, body) : api.post('/api/employees', body));
  const saveButton = form.querySelector('[type="submit"]');
  saveButton.disabled = true;
  try {
    let { ok, status, data } = await submit(payload);
    if (status === 409 && data.code === 'orphaned_shifts') {
      // Removing a position deletes that employee's shifts in it; make the user say so.
      const which = data.shift_count === 1 ? 'that shift' : 'those shifts';
      if (!window.confirm(`${data.error} Remove ${which} and save?`)) return;
      ({ ok, data } = await submit({ ...payload, remove_orphaned_shifts: true }));
    }
    if (!ok) { showError(data.error || 'Unable to save employee'); return; }
    const removed = data.removed_shifts ? ` · ${plural(data.removed_shifts, 'shift')} removed` : '';
    showToast((id ? 'Employee updated' : 'Employee added') + removed);
    resetForm();
    await loadEmployees();
  } finally {
    saveButton.disabled = false;
  }
});

$('#new-employee').addEventListener('click', () => { resetForm(); $('#name').focus(); });
$('#cancel-edit').addEventListener('click', resetForm);

// --- employee list -----------------------------------------------------------

function renderEmployees() {
  $('#employee-count').textContent = plural(employees.length, 'employee');
  if (!employees.length) {
    list.innerHTML = '<p class="empty">No employees yet. Add your first team member.</p>';
    return;
  }
  const editingId = Number($('#employee-id').value);
  list.innerHTML = employees.map(employee => `
    <article class="employee-card${employee.id === editingId ? ' editing' : ''}" data-id="${employee.id}">
      <span class="employee-swatch" style="background:${escapeHtml(employee.color)}"></span>
      <div>
        <p class="employee-name">${escapeHtml(employee.name)}</p>
        <p class="employee-meta">${escapeHtml(employee.employment_type)} · ${escapeHtml(employee.positions.join(', '))} · ${escapeHtml(availabilityText(employee.availability))}</p>
      </div>
      <div class="card-actions">
        <button type="button" data-edit="${employee.id}">Edit</button>
        <button type="button" data-delete="${employee.id}">Delete</button>
      </div>
    </article>`).join('');
}

list.addEventListener('click', async event => {
  const button = event.target.closest('button[data-edit], button[data-delete]');
  if (!button) return;
  const employee = employees.find(item => item.id === Number(button.dataset.edit || button.dataset.delete));
  if (!employee) return;
  if (button.dataset.edit) { editEmployee(employee); return; }
  if (!window.confirm(`Delete ${employee.name}? Their saved shifts will be removed too.`)) return;
  const { ok, data } = await api.delete(`/api/employees/${employee.id}`);
  if (!ok) { showError(data.error || 'Unable to delete employee'); return; }
  showToast('Employee deleted');
  if (Number($('#employee-id').value) === employee.id) resetForm();
  await loadEmployees();
});

async function loadEmployees() {
  const { ok, data } = await api.get('/api/employees');
  if (!ok) throw new Error(data.error);
  employees = data;
  renderEmployees();
  if (!$('#employee-id').value) $('#color').value = unusedColor();
}

// --- operating hours ---------------------------------------------------------

function renderHours(hours) {
  $('#hours-list').innerHTML = DAYS.map(day => {
    const value = hours[day];
    return `<div class="hours-row">
      <strong>${day}</strong>
      <label><span class="visually-hidden">Open time for ${day}</span><input type="time" data-open="${day}" value="${escapeHtml(value?.open || '09:00')}" ${value ? '' : 'disabled'}></label>
      <span class="hours-divider">to</span>
      <label><span class="visually-hidden">Close time for ${day}</span><input type="time" data-close="${day}" value="${escapeHtml(value?.close || '21:00')}" ${value ? '' : 'disabled'}></label>
      <label class="closed-toggle"><input type="checkbox" data-closed="${day}" ${value ? '' : 'checked'}> Closed</label>
    </div>`;
  }).join('');
}

$('#hours-list').addEventListener('change', event => {
  const day = event.target.dataset.closed;
  if (!day) return;
  $(`[data-open="${day}"]`).disabled = event.target.checked;
  $(`[data-close="${day}"]`).disabled = event.target.checked;
});

$('#hours-form').addEventListener('submit', async event => {
  event.preventDefault();
  const hours = Object.fromEntries(DAYS.map(day => [
    day,
    $(`[data-closed="${day}"]`).checked ? null : { open: $(`[data-open="${day}"]`).value, close: $(`[data-close="${day}"]`).value },
  ]));
  const { ok, data } = await api.put('/api/settings', hours);
  if (ok) showToast('Operating hours saved');
  else showError(data.error || 'Unable to save hours');
});

$('#clear-schedule').addEventListener('click', async () => {
  if (!window.confirm('Clear every saved shift from the weekly schedule? Employees and store settings will not be changed.')) return;
  const { ok, data } = await api.delete('/api/shifts');
  if (ok) showToast(`${plural(data.deleted_count, 'shift')} cleared`);
  else showError(data.error || 'Unable to clear schedule');
});

async function loadHours() {
  const { ok, data } = await api.get('/api/settings');
  if (!ok) throw new Error(data.error);
  renderHours(data);
}

// --- boot --------------------------------------------------------------------

Promise.all([loadEmployees(), loadHours()]).catch(error => showError(error.message || 'Unable to load employee directory'));
