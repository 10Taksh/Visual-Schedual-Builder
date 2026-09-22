import { api } from './lib/api.js';
import { createAvailabilityEditor } from './lib/availability-editor.js';
import { confirmDialog } from './lib/dialog.js';
import { $, $$, DAYS, META, escapeHtml, plural, withBusy } from './lib/dom.js';
import { availabilityRanges, formatTime12 } from './lib/time.js';
import { showError, showToast } from './lib/toast.js';

const form = $('#employee-form');
const list = $('#employee-list');
const palette = META.palette || [];
const positionColors = Object.fromEntries($$('#positions .check').map(label => [label.querySelector('input').value, label.querySelector('.dot').style.getPropertyValue('--dot-color')]));
const availabilityEditor = createAvailabilityEditor($('#availability-editor'));
let employees = [];

// --- employee form -----------------------------------------------------------

function unusedColor() {
  const used = new Set(employees.map(employee => employee.color.toUpperCase()));
  return palette.find(color => !used.has(color)) || palette[employees.length % palette.length] || '#E07A5F';
}

function setColor(value) {
  $('#color').value = value;
  $('#color-code').textContent = value.toUpperCase();
}

function resetForm() {
  form.reset();
  $('#employee-id').value = '';
  $('#form-title').textContent = 'Add employee';
  $('#cancel-edit').hidden = true;
  $('#availability-error').hidden = true;
  availabilityEditor.setValue('Open');
  setColor(unusedColor());
  $$('#positions input').forEach(input => { input.checked = false; });
  $$('.employee-card.editing').forEach(card => card.classList.remove('editing'));
}

function editEmployee(employee) {
  $('#employee-id').value = employee.id;
  $('#form-title').textContent = `Edit ${employee.name}`;
  $('#cancel-edit').hidden = false;
  $('#name').value = employee.name;
  $('#employment-type').value = employee.employment_type;
  availabilityEditor.setValue(employee.availability);
  setColor(employee.color);
  $$('#positions input').forEach(input => { input.checked = employee.positions.includes(input.value); });
  $$('.employee-card').forEach(card => card.classList.toggle('editing', Number(card.dataset.id) === employee.id));
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  $('#name').focus();
}

$('#color').addEventListener('input', event => { $('#color-code').textContent = event.target.value.toUpperCase(); });

form.addEventListener('submit', async event => {
  event.preventDefault();
  const id = $('#employee-id').value;
  const availability = availabilityEditor.getValue();
  $('#availability-error').hidden = !availability.error;
  $('#availability-error').textContent = availability.error || '';
  if (availability.error) return;
  if (!$('#name').value.trim()) { showError('Name is required'); $('#name').focus(); return; }

  const payload = {
    name: $('#name').value,
    employment_type: $('#employment-type').value,
    positions: $$('#positions input:checked').map(input => input.value),
    availability: availability.value,
    color: $('#color').value,
  };
  const submit = body => (id ? api.put(`/api/employees/${id}`, body) : api.post('/api/employees', body));

  await withBusy($('#save-employee'), async () => {
    let { ok, status, data } = await submit(payload);
    if (status === 409 && data.code === 'orphaned_shifts') {
      // Removing a position deletes that employee's shifts in it; make the user say so.
      const confirmed = await confirmDialog({
        title: 'Remove saved shifts?',
        message: `${data.error} Saving will remove ${data.shift_count === 1 ? 'that shift' : 'those shifts'} from the schedule.`,
        confirmLabel: `Remove and save`,
        danger: true,
      });
      if (!confirmed) return;
      ({ ok, data } = await submit({ ...payload, remove_orphaned_shifts: true }));
    }
    if (!ok) { showError(data.error || 'Unable to save employee'); return; }
    const removed = data.removed_shifts ? ` · ${plural(data.removed_shifts, 'shift')} removed` : '';
    showToast((id ? 'Employee updated' : 'Employee added') + removed);
    resetForm();
    await loadEmployees();
  });
});

$('#new-employee').addEventListener('click', () => { resetForm(); form.scrollIntoView({ behavior: 'smooth', block: 'start' }); $('#name').focus(); });
$('#cancel-edit').addEventListener('click', resetForm);
$('#reset-form').addEventListener('click', resetForm);

// --- employee list -----------------------------------------------------------

function availabilityChips(availability) {
  if (!availability || typeof availability !== 'object') return '<span class="chip open">Open all week</span>';
  return DAYS.map(day => {
    const ranges = availabilityRanges(availability, day);
    if (ranges === null) return '';
    const label = day.slice(0, 3);
    if (!ranges.length) return `<span class="chip off">${label} off</span>`;
    return `<span class="chip">${label} ${ranges.map(([start, end]) => `${formatTime12(start)}–${formatTime12(end)}`).join(', ')}</span>`;
  }).join('');
}

function renderEmployees() {
  $('#employee-count').textContent = plural(employees.length, 'employee');
  if (!employees.length) {
    list.innerHTML = '<p class="empty">No employees yet. Add your first team member with the form.</p>';
    return;
  }
  const editingId = Number($('#employee-id').value);
  list.innerHTML = employees.map(employee => `
    <article class="card employee-card${employee.id === editingId ? ' editing' : ''}" data-id="${employee.id}">
      <span class="employee-swatch" style="background:${escapeHtml(employee.color)}"></span>
      <div class="employee-main">
        <div class="employee-title">
          <h3 class="employee-name">${escapeHtml(employee.name)}</h3>
          <span class="badge">${escapeHtml(employee.employment_type)}</span>
        </div>
        <div class="employee-tags">
          ${employee.positions.map(position => `<span class="chip"><span class="dot" style="--dot-color:${escapeHtml(positionColors[position] || '')}"></span>${escapeHtml(position)}</span>`).join('')}
        </div>
        <div class="employee-availability">${availabilityChips(employee.availability)}</div>
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

  const confirmed = await confirmDialog({
    title: `Delete ${employee.name}?`,
    message: 'Their saved shifts will be removed from every schedule. This cannot be undone.',
    confirmLabel: 'Delete employee',
    danger: true,
  });
  if (!confirmed) return;
  const { ok, data } = await api.delete(`/api/employees/${employee.id}`);
  if (!ok) { showError(data.error || 'Unable to delete employee'); return; }
  showToast(`${employee.name} deleted`);
  if (Number($('#employee-id').value) === employee.id) resetForm();
  await loadEmployees();
});

async function loadEmployees() {
  const { ok, data } = await api.get('/api/employees');
  if (!ok) throw new Error(data.error);
  employees = data;
  renderEmployees();
  if (!$('#employee-id').value) setColor(unusedColor());
}

// --- operating hours ---------------------------------------------------------

function renderHours(hours) {
  $('#hours-list').innerHTML = DAYS.map(day => {
    const value = hours[day];
    return `<div class="hours-row${value ? '' : ' is-closed'}">
      <strong>${day.slice(0, 3)}</strong>
      <label><span class="visually-hidden">Open time for ${day}</span><input type="time" data-open="${day}" step="900" value="${escapeHtml(value?.open || '09:00')}" ${value ? '' : 'disabled'}></label>
      <span class="hours-divider">–</span>
      <label><span class="visually-hidden">Close time for ${day}</span><input type="time" data-close="${day}" step="900" value="${escapeHtml(value?.close || '21:00')}" ${value ? '' : 'disabled'}></label>
      <label class="check closed-toggle"><input type="checkbox" data-closed="${day}" ${value ? '' : 'checked'}> Closed</label>
    </div>`;
  }).join('');
}

$('#hours-list').addEventListener('change', event => {
  const day = event.target.dataset.closed;
  if (!day) return;
  $(`[data-open="${day}"]`).disabled = event.target.checked;
  $(`[data-close="${day}"]`).disabled = event.target.checked;
  event.target.closest('.hours-row').classList.toggle('is-closed', event.target.checked);
});

function renderBreakRule(settings) {
  $('#break-threshold').value = (settings.break_threshold_minutes / 60).toString();
  $('#break-duration').value = settings.break_duration_minutes;
}

$('#hours-form').addEventListener('submit', async event => {
  event.preventDefault();
  const payload = {
    operating_hours: Object.fromEntries(DAYS.map(day => [
      day,
      $(`[data-closed="${day}"]`).checked ? null : { open: $(`[data-open="${day}"]`).value, close: $(`[data-close="${day}"]`).value },
    ])),
    break_threshold_minutes: Math.round(Number($('#break-threshold').value || 0) * 60),
    break_duration_minutes: Math.round(Number($('#break-duration').value || 0)),
  };
  await withBusy($('#save-hours'), async () => {
    const { ok, data } = await api.put('/api/settings', payload);
    if (!ok) { showError(data.error || 'Unable to save settings'); return; }
    renderBreakRule(data);
    showToast('Store settings saved');
  });
});

$('#clear-schedule').addEventListener('click', async event => {
  const confirmed = await confirmDialog({
    title: 'Clear every saved shift?',
    message: 'All shifts in every position will be removed. Employees and store hours are not affected.',
    confirmLabel: 'Clear all shifts',
    danger: true,
  });
  if (!confirmed) return;
  await withBusy(event.currentTarget, async () => {
    const { ok, data } = await api.delete('/api/shifts');
    if (ok) showToast(`${plural(data.deleted_count, 'shift')} cleared`);
    else showError(data.error || 'Unable to clear schedule');
  });
});

async function loadHours() {
  const { ok, data } = await api.get('/api/settings');
  if (!ok) throw new Error(data.error);
  renderHours(data.operating_hours);
  renderBreakRule(data);
}

// --- boot --------------------------------------------------------------------

list.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
resetForm();
Promise.all([loadEmployees(), loadHours()]).catch(error => showError(error.message || 'Unable to load employee directory'));
