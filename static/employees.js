const form = document.querySelector('#employee-form');
const list = document.querySelector('#employee-list');
const toast = document.querySelector('#toast');
let employees = [];
const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('visible');
  window.setTimeout(() => toast.classList.remove('visible'), 3000);
}

function availabilityText(value) {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

function renderEmployees() {
  document.querySelector('#employee-count').textContent = `${employees.length} employee${employees.length === 1 ? '' : 's'}`;
  if (!employees.length) {
    list.innerHTML = '<p class="empty">No employees yet. Add your first team member.</p>';
    return;
  }
  list.innerHTML = employees.map(employee => `
    <article class="employee-card">
      <span class="employee-swatch" style="background:${employee.color}"></span>
      <div>
        <p class="employee-name">${employee.name}</p>
        <p class="employee-meta">${employee.employment_type} · ${employee.positions.join(', ')} · ${availabilityText(employee.availability)}</p>
      </div>
      <div class="card-actions">
        <button type="button" data-edit="${employee.id}">Edit</button>
        <button type="button" data-delete="${employee.id}">Delete</button>
      </div>
    </article>`).join('');
}

function resetForm() {
  form.reset();
  document.querySelector('#employee-id').value = '';
  document.querySelector('#form-title').textContent = 'Add employee';
  document.querySelector('#availability').value = 'Open';
  document.querySelectorAll('#positions input').forEach(input => { input.checked = false; });
}

function editEmployee(employee) {
  document.querySelector('#employee-id').value = employee.id;
  document.querySelector('#form-title').textContent = 'Edit employee';
  document.querySelector('#name').value = employee.name;
  document.querySelector('#employment-type').value = employee.employment_type;
  document.querySelector('#availability').value = availabilityText(employee.availability);
  document.querySelector('#color').value = employee.color;
  document.querySelectorAll('#positions input').forEach(input => { input.checked = employee.positions.includes(input.value); });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function loadPositions() {
  const response = await fetch('/api/positions');
  const positions = await response.json();
  document.querySelector('#positions').innerHTML = positions.map(position => `
    <label class="position-option"><input type="checkbox" value="${position}"> ${position}</label>`).join('');
}

async function loadEmployees() {
  const response = await fetch('/api/employees');
  employees = await response.json();
  renderEmployees();
}

function renderHours(hours) {
  document.querySelector('#hours-list').innerHTML = days.map(day => {
    const value = hours[day];
    return `<div class="hours-row">
      <strong>${day}</strong>
      <label><span class="visually-hidden">Open time for ${day}</span><input type="time" data-open="${day}" value="${value?.open || '09:00'}" ${value ? '' : 'disabled'}></label>
      <span class="hours-divider">to</span>
      <label><span class="visually-hidden">Close time for ${day}</span><input type="time" data-close="${day}" value="${value?.close || '21:00'}" ${value ? '' : 'disabled'}></label>
      <label class="closed-toggle"><input type="checkbox" data-closed="${day}" ${value ? '' : 'checked'}> Closed</label>
    </div>`;
  }).join('');
}

async function loadHours() {
  const response = await fetch('/api/settings');
  if (!response.ok) throw new Error('Unable to load operating hours');
  renderHours(await response.json());
}

document.querySelector('#hours-list').addEventListener('change', event => {
  if (!event.target.dataset.closed) return;
  const day = event.target.dataset.closed;
  document.querySelector(`[data-open="${day}"]`).disabled = event.target.checked;
  document.querySelector(`[data-close="${day}"]`).disabled = event.target.checked;
});

document.querySelector('#hours-form').addEventListener('submit', async event => {
  event.preventDefault();
  const hours = Object.fromEntries(days.map(day => {
    const closed = document.querySelector(`[data-closed="${day}"]`).checked;
    return [day, closed ? null : {
      open: document.querySelector(`[data-open="${day}"]`).value,
      close: document.querySelector(`[data-close="${day}"]`).value,
    }];
  }));
  const response = await fetch('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(hours) });
  const result = await response.json();
  showToast(response.ok ? 'Operating hours saved' : result.error || 'Unable to save hours');
});

document.querySelector('#clear-schedule').addEventListener('click', async () => {
  const confirmed = window.confirm('Clear every saved shift from the weekly schedule? Employees and store settings will not be changed.');
  if (!confirmed) return;
  const response = await fetch('/api/shifts', { method: 'DELETE' });
  const result = await response.json();
  showToast(response.ok ? `${result.deleted_count} shift${result.deleted_count === 1 ? '' : 's'} cleared` : result.error || 'Unable to clear schedule');
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  const id = document.querySelector('#employee-id').value;
  const payload = {
    name: document.querySelector('#name').value,
    employment_type: document.querySelector('#employment-type').value,
    positions: [...document.querySelectorAll('#positions input:checked')].map(input => input.value),
    availability: document.querySelector('#availability').value,
    color: document.querySelector('#color').value,
  };
  const response = await fetch(id ? `/api/employees/${id}` : '/api/employees', {
    method: id ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) { showToast(result.error || 'Unable to save employee'); return; }
  showToast(id ? 'Employee updated' : 'Employee added');
  resetForm();
  await loadEmployees();
});

list.addEventListener('click', async event => {
  const employeeId = event.target.dataset.edit || event.target.dataset.delete;
  if (!employeeId) return;
  const employee = employees.find(item => item.id === Number(employeeId));
  if (event.target.dataset.edit) { editEmployee(employee); return; }
  if (!window.confirm(`Delete ${employee.name}?`)) return;
  const response = await fetch(`/api/employees/${employeeId}`, { method: 'DELETE' });
  if (response.ok) { showToast('Employee deleted'); await loadEmployees(); }
});

document.querySelector('#new-employee').addEventListener('click', resetForm);
document.querySelector('#cancel-edit').addEventListener('click', resetForm);

Promise.all([loadPositions(), loadEmployees(), loadHours()]).catch(() => showToast('Unable to load employee directory'));