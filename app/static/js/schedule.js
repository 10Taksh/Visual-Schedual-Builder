import { api } from './lib/api.js';
import { $, $$, META, escapeHtml } from './lib/dom.js';
import { availabilityRanges, availabilityText, clockToMinutes, formatDuration, formatTime12, formatTimeShort, minutesToClock } from './lib/time.js';
import { showError } from './lib/toast.js';

const activePosition = document.body.dataset.position;
const employeePicker = $('#employee-picker');
const dayPicker = $('#day-picker');
const employeeDetails = $('#employee-details');

const SLOT = META.slot_minutes || 15;
const MINIMUM = META.minimum_shift_minutes || 30;
const BREAK_THRESHOLD = META.break_threshold_minutes || 300;
const BREAK_DURATION = META.break_duration_minutes || 30;
const EMPTY_DAY = '<p class="empty-day">No shifts yet</p>';

let storeHours = {};
const employeesById = new Map();

// --- helpers -----------------------------------------------------------------

/** Store open/close for a day in minutes, or null when closed. */
function dayWindow(day) {
  const hours = storeHours[day];
  return hours ? { open: clockToMinutes(hours.open), close: clockToMinutes(hours.close) } : null;
}

function breakFor(durationMinutes) {
  return durationMinutes >= BREAK_THRESHOLD ? BREAK_DURATION : 0;
}

function shiftLabel(start, end) {
  const duration = end - start;
  const breakMinutes = breakFor(duration);
  const breakText = breakMinutes ? ` · ${breakMinutes}m break` : '';
  return `${formatTime12(start)}–${formatTime12(end)}${breakText} (${formatDuration(duration - breakMinutes)} paid)`;
}

/**
 * Where a brand-new shift should start: the first availability window that
 * overlaps store hours, or the whole store day when the employee is open.
 */
function defaultShiftWindow(employee, day, storeWindow) {
  const ranges = availabilityRanges(employee.availability, day);
  if (ranges === null) return { start: storeWindow.open, end: storeWindow.close };
  for (const [start, end] of ranges) {
    const clampedStart = Math.max(storeWindow.open, start);
    const clampedEnd = Math.min(storeWindow.close, end);
    if (clampedEnd - clampedStart >= MINIMUM) return { start: clampedStart, end: clampedEnd };
  }
  return null;
}

function renderDayHeaders() {
  $$('[data-day-hours]').forEach(element => {
    const storeWindow = dayWindow(element.dataset.dayHours);
    element.textContent = storeWindow ? `${formatTimeShort(storeWindow.open)}–${formatTimeShort(storeWindow.close)}` : 'Closed';
    element.closest('.day-column').classList.toggle('closed', !storeWindow);
  });
}

// --- employee picker ---------------------------------------------------------

function renderEmployees(employees) {
  employeesById.clear();
  employeePicker.innerHTML = '<option value="">Select employee</option>';
  for (const employee of employees) {
    employeesById.set(employee.id, employee);
    const option = document.createElement('option');
    option.value = employee.id;
    option.textContent = employee.name;
    employeePicker.appendChild(option);
  }
}

function showEmployeeDetails(employee) {
  if (!employee) {
    employeeDetails.innerHTML = '<p class="details-empty">Select an employee to see their work details.</p>';
    return;
  }
  employeeDetails.innerHTML = `
    <div class="details-heading">
      <span class="details-swatch" style="background:${escapeHtml(employee.color)}"></span>
      <strong>${escapeHtml(employee.name)}</strong>
    </div>
    <div class="details-grid">
      <span>Can work</span><strong>${escapeHtml(employee.positions.join(', '))}</strong>
      <span>Availability</span><strong>${escapeHtml(availabilityText(employee.availability))}</strong>
      <span>Employment</span><strong>${escapeHtml(employee.employment_type)}</strong>
    </div>`;
}

employeePicker.addEventListener('change', () => showEmployeeDetails(employeesById.get(Number(employeePicker.value))));

$('#add-shift').addEventListener('click', () => {
  const employee = employeesById.get(Number(employeePicker.value));
  if (!employee) { showError('Choose an employee first.'); return; }
  const day = dayPicker.value;
  if (!dayWindow(day)) { showError(`The store is closed on ${day}.`); return; }
  if (addShiftCard(employee, day)) {
    employeePicker.value = '';
    showEmployeeDetails(null);
  }
});

// --- shift cards -------------------------------------------------------------

function addShiftCard(employee, day, shift = null) {
  const body = $(`[data-day-body="${day}"]`);
  const storeWindow = dayWindow(day) || { open: 9 * 60, close: 21 * 60 };
  let start;
  let end;
  if (shift) {
    // Keep saved shifts inside the slider's range even if store hours were narrowed later.
    start = Math.min(Math.max(storeWindow.open, clockToMinutes(shift.start_time)), storeWindow.close - MINIMUM);
    end = Math.max(Math.min(storeWindow.close, clockToMinutes(shift.end_time)), storeWindow.open + MINIMUM);
  } else {
    const initial = defaultShiftWindow(employee, day, storeWindow);
    if (!initial) {
      showError(`${employee.name} is not available on ${day} during store hours.`);
      return false;
    }
    ({ start, end } = initial);
  }

  body.querySelector('.empty-day')?.remove();
  const card = document.createElement('div');
  card.className = 'shift-card';
  card.style.setProperty('--employee-color', employee.color);
  card.dataset.shiftId = shift?.id || '';
  card.innerHTML = `
    <div class="shift-heading">
      <strong>${escapeHtml(employee.name)}</strong>
      <button type="button" class="remove-shift" aria-label="Remove ${escapeHtml(employee.name)} from ${day}">×</button>
    </div>
    <span class="shift-position">${escapeHtml(activePosition)}</span>
    <div class="shift-time">${shiftLabel(start, end)}</div>
    <div class="shift-slider" aria-label="${escapeHtml(employee.name)} shift hours"></div>
    <div class="shift-save-status">${shift ? 'Saved' : 'Saving…'}</div>`;
  body.appendChild(card);

  const status = card.querySelector('.shift-save-status');
  const timeLabel = card.querySelector('.shift-time');
  const slider = card.querySelector('.shift-slider');
  const setStatus = (text, isError = false) => { status.textContent = text; status.classList.toggle('error', isError); };

  window.noUiSlider.create(slider, {
    start: [start, end],
    connect: true,
    step: SLOT,
    margin: MINIMUM,
    range: { min: storeWindow.open, max: storeWindow.close },
    format: { to: value => value, from: value => Number(value) },
  });

  let saveTimer;
  const save = values => {
    clearTimeout(saveTimer);
    saveTimer = window.setTimeout(async () => {
      const [from, to] = values.map(Number);
      const payload = { employee_id: employee.id, position: activePosition, day_of_week: day, start_time: minutesToClock(from), end_time: minutesToClock(to) };
      const { ok, data } = card.dataset.shiftId ? await api.put(`/api/shifts/${card.dataset.shiftId}`, payload) : await api.post('/api/shifts', payload);
      if (!ok) {
        setStatus('Not saved', true);
        showError(data.error || 'Unable to save shift');
        return;
      }
      card.dataset.shiftId = data.id;
      setStatus('Saved');
      timeLabel.textContent = shiftLabel(from, to);
    }, 180);
  };

  // noUiSlider fires "update" once on creation; that is not a user edit.
  let ready = false;
  slider.noUiSlider.on('update', values => {
    if (!ready) return;
    const [from, to] = values.map(Number);
    timeLabel.textContent = shiftLabel(from, to);
    setStatus('Unsaved');
  });
  ready = true;
  slider.noUiSlider.on('change', save);
  if (!shift) save([start, end]);

  card.querySelector('.remove-shift').addEventListener('click', async event => {
    const button = event.currentTarget;
    if (card.dataset.shiftId) {
      button.disabled = true;
      setStatus('Removing…');
      const { ok, status: code, data } = await api.delete(`/api/shifts/${card.dataset.shiftId}`);
      if (!ok && code !== 404) {
        button.disabled = false;
        setStatus('Saved');
        showError(data.error || 'Unable to remove shift');
        return;
      }
    }
    card.remove();
    if (!body.querySelector('.shift-card')) body.innerHTML = EMPTY_DAY;
  });
  return true;
}

// --- boot --------------------------------------------------------------------

async function loadStoreHours() {
  const { ok, data } = await api.get('/api/settings');
  if (!ok) throw new Error(data.error || 'Unable to load store hours');
  storeHours = data;
  renderDayHeaders();
}

async function loadEmployees() {
  const { ok, data } = await api.get(`/api/employees?position=${encodeURIComponent(activePosition)}`);
  if (!ok) throw new Error(data.error || 'Unable to load employees');
  renderEmployees(data);
  if (!data.length) employeePicker.innerHTML = '<option value="">No employees assigned to this position</option>';
}

async function loadShifts() {
  const { ok, data } = await api.get(`/api/shifts?position=${encodeURIComponent(activePosition)}`);
  if (!ok) throw new Error(data.error || 'Unable to load shifts');
  for (const shift of data) {
    addShiftCard({ id: shift.employee_id, name: shift.employee_name, color: shift.employee_color }, shift.day_of_week, shift);
  }
}

(async () => {
  try {
    await loadStoreHours();
    await Promise.all([loadEmployees(), loadShifts()]);
  } catch (error) {
    showError(error.message || 'Unable to load the schedule');
  }
})();
