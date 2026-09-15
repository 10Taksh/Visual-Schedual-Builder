const activePosition = document.body.dataset.position;
const employeePicker = document.querySelector('#employee-picker');
const dayPicker = document.querySelector('#day-picker');
const employeeDetails = document.querySelector('#employee-details');
const emptyState = '<p class="empty-day">No shifts yet</p>';
let storeHours = {};

function availabilityText(availability) {
  if (typeof availability === 'string') return availability;
  return Object.entries(availability || {})
    .map(([day, hours]) => `${day}: ${typeof hours === 'string' ? hours : JSON.stringify(hours)}`)
    .join(' · ') || 'Open';
}

function showEmployeeDetails(employee) {
  if (!employee) {
    employeeDetails.innerHTML = '<p class="details-empty">Select an employee to see their work details.</p>';
    return;
  }
  employeeDetails.innerHTML = `
    <div class="details-heading">
      <span class="details-swatch" style="background:${employee.color}"></span>
      <strong>${employee.name}</strong>
    </div>
    <div class="details-grid">
      <span>Can work</span><strong>${employee.positions.join(', ')}</strong>
      <span>Availability</span><strong>${availabilityText(employee.availability)}</strong>
      <span>Employment</span><strong>${employee.employment_type}</strong>
    </div>`;
}

function minutesToTime(minutes) {
  const hours = Math.floor(minutes / 60).toString().padStart(2, '0');
  const remainder = Math.round(minutes % 60).toString().padStart(2, '0');
  return `${hours}:${remainder}`;
}

function formatTime12(minutes) {
  const totalMinutes = Math.round(minutes) % (24 * 60);
  const hour = Math.floor(totalMinutes / 60);
  const minute = totalMinutes % 60;
  const suffix = hour >= 12 ? 'PM' : 'AM';
  const displayHour = hour % 12 || 12;
  return `${displayHour}:${minute.toString().padStart(2, '0')} ${suffix}`;
}

function shiftLabel(start, end, breakDeduction) {
  const duration = end - start;
  const breakText = breakDeduction ? ' · 30m break' : '';
  return `${formatTime12(start)}–${formatTime12(end)}${breakText} (${Math.floor((duration - (breakDeduction ? 30 : 0)) / 60)}h paid)`;
}

function createTimeSlider(element, start = 9, end = 17, minimum = 0, maximum = 24) {
  if (!window.noUiSlider || !element) return;
  window.noUiSlider.create(element, {
    start: [start, end],
    connect: true,
      step: 0.25,
    range: { min: minimum, max: maximum },
    format: { to: value => value, from: value => Number(value) },
  });
}

function dayHours(day) {
  const hours = storeHours[day];
  if (!hours) return null;
  const open = Number(hours.open.slice(0, 2)) + Number(hours.open.slice(3)) / 60;
  const close = Number(hours.close.slice(0, 2)) + Number(hours.close.slice(3)) / 60;
  return { open, close };
}

function renderEmployees(employees) {
  employeePicker.innerHTML = '<option value="">Select employee</option>';
  employees.forEach(employee => {
    const option = document.createElement('option');
    option.value = employee.id;
    option.textContent = employee.name;
    option.dataset.employee = JSON.stringify(employee);
    employeePicker.appendChild(option);
  });
}

function addEmployeeToDay(employee, day, shift = null) {
  const body = document.querySelector(`[data-day="${day}"] .day-body`);
  body.querySelector('.empty-day')?.remove();
  const card = document.createElement('div');
  card.className = 'shift-card';
  card.style.setProperty('--employee-color', employee.color);
  card.dataset.shiftId = shift?.id || '';
  const hours = dayHours(day) || { open: 9, close: 21 };
  const storedStart = shift ? Number(shift.start_time.slice(0, 2)) + Number(shift.start_time.slice(3)) / 60 : hours.open;
  const storedEnd = shift ? Number(shift.end_time.slice(0, 2)) + Number(shift.end_time.slice(3)) / 60 : hours.close;
  const startMinutes = Math.min(Math.max(hours.open * 60, storedStart * 60), hours.close * 60 - 30);
  const endMinutes = Math.max(Math.min(hours.close * 60, storedEnd * 60), hours.open * 60 + 30);
  card.innerHTML = `
    <div class="shift-heading">
      <strong>${employee.name}</strong>
      <button type="button" class="remove-shift" aria-label="Remove ${employee.name}">×</button>
    </div>
    <span class="shift-position">${activePosition}</span>
    <div class="shift-time">${shiftLabel(startMinutes, endMinutes, shift?.break_deduction)}</div>
    <div class="shift-slider"></div>
    <div class="shift-save-status">${shift ? 'Saved' : 'Saving...'}</div>`;
  const slider = card.querySelector('.shift-slider');
  createTimeSlider(slider, startMinutes / 60, endMinutes / 60, hours.open, hours.close);
  let saveTimer;
  const save = async values => {
    clearTimeout(saveTimer);
    saveTimer = window.setTimeout(async () => {
      const [start, end] = values.map(Number);
      const response = await fetch(card.dataset.shiftId ? `/api/shifts/${card.dataset.shiftId}` : '/api/shifts', {
        method: card.dataset.shiftId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ employee_id: employee.id, position: activePosition, day_of_week: day, start_time: minutesToTime(start * 60), end_time: minutesToTime(end * 60) }),
      });
      const result = await response.json();
      if (!response.ok) {
        card.querySelector('.shift-save-status').textContent = 'Not saved';
        showConflict(result.error || 'Unable to save shift');
        return;
      }
      card.dataset.shiftId = result.id;
      card.querySelector('.shift-save-status').textContent = 'Saved';
      card.querySelector('.shift-time').textContent = shiftLabel(start * 60, end * 60, result.break_deduction);
    }, 180);
  };
  slider.noUiSlider.on('update', (values) => {
    const [start, end] = values.map(Number);
    card.querySelector('.shift-time').textContent = shiftLabel(start * 60, end * 60, end - start >= 5);
    card.querySelector('.shift-save-status').textContent = 'Unsaved';
  });
  slider.noUiSlider.on('change', save);
  if (!shift) save([startMinutes / 60, endMinutes / 60]);
  card.querySelector('.remove-shift').addEventListener('click', () => {
    if (card.dataset.shiftId) {
      fetch(`/api/shifts/${card.dataset.shiftId}`, { method: 'DELETE' });
    }
    card.remove();
    if (!body.querySelector('.shift-card')) body.innerHTML = emptyState;
  });
  body.appendChild(card);
}

function showConflict(message) {
  window.alert(message);
}

async function loadEmployees() {
  const response = await fetch(`/api/employees?position=${encodeURIComponent(activePosition)}`);
  if (!response.ok) throw new Error('Unable to load employees');
  renderEmployees(await response.json());
}

async function loadShifts() {
  const response = await fetch(`/api/shifts?position=${encodeURIComponent(activePosition)}`);
  if (!response.ok) throw new Error('Unable to load shifts');
  const shifts = await response.json();
  shifts.forEach(shift => addEmployeeToDay({ id: shift.employee_id, name: shift.employee_name, color: shift.employee_color }, shift.day_of_week, shift));
}

async function loadStoreHours() {
  const response = await fetch('/api/settings');
  if (!response.ok) throw new Error('Unable to load store hours');
  storeHours = await response.json();
}

document.querySelector('#add-shift').addEventListener('click', () => {
  const option = employeePicker.selectedOptions[0];
  if (!option?.dataset.employee) return;
  if (!dayHours(dayPicker.value)) {
    showConflict(`The store is closed on ${dayPicker.value}.`);
    return;
  }
  addEmployeeToDay(JSON.parse(option.dataset.employee), dayPicker.value);
  employeePicker.value = '';
  showEmployeeDetails(null);
});

employeePicker.addEventListener('change', () => {
  const option = employeePicker.selectedOptions[0];
  showEmployeeDetails(option?.dataset.employee ? JSON.parse(option.dataset.employee) : null);
});

async function initializeSchedule() {
  try {
    await loadStoreHours();
    await Promise.all([loadEmployees(), loadShifts()]);
  } catch (error) {
    employeePicker.innerHTML = '<option value="">No employees assigned to this position</option>';
  }
}

initializeSchedule();