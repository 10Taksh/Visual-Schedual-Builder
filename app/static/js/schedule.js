/**
 * Schedule board: a vertical time axis per day with shift blocks positioned by time.
 *
 * Interactions
 *   - roster: click a person to select them; the board shades where they are unavailable
 *   - click / drag on an empty part of a day column: create a shift for the selected person
 *   - "+" in a day header: add the selected person with a sensible default window
 *   - drag a block: move it (also across days); drag its top/bottom edge: resize
 *   - click a block (or Enter/Space): open the editor for exact times, day, removal, or duplication
 *   - arrow keys on a focused block: nudge by one slot; Shift+arrow resizes the end
 *   - "⋯" in a day header: copy the day's shifts to other days, or clear the day
 *   - removing a shift is immediate, with an Undo in the toast
 *
 * Every change is validated client-side first (store hours, availability, overlaps
 * across positions), then saved; the server remains the final authority.
 */

import { api } from './lib/api.js';
import { confirmDialog } from './lib/dialog.js';
import { $, $$, DAYS, META, clamp, escapeHtml, plural } from './lib/dom.js';
import { availabilityRanges, availabilityText, clockToMinutes, formatDuration, formatTime12, formatTimeShort, minutesToClock } from './lib/time.js';
import { showError, showToast } from './lib/toast.js';

const POSITION = document.body.dataset.position;
const POSITION_COLOR = document.body.dataset.positionColor;
const SLOT = META.slot_minutes || 15;
const MINIMUM = META.minimum_shift_minutes || 30;
const DEFAULT_ADD_MINUTES = 8 * 60;    // "+" button
const DEFAULT_CLICK_MINUTES = 4 * 60;  // single click on the board
const WEEKLY_HOURS_WARNING = META.weekly_hours_warning_minutes || 40 * 60;
const UNDO_WINDOW_MS = 6000;

const HOUR_PX = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--board-hour-px')) || 64;
const PX_PER_MIN = HOUR_PX / 60;

const board = $('#board');
const boardBody = $('#board-body');
const editor = $('#shift-editor');
const dayMenu = $('#day-menu');
const singleDayQuery = window.matchMedia('(max-width: 900px)');

const state = {
  hours: {},                 // day -> {open, close} in minutes, or null when closed
  axis: { start: 9 * 60, end: 21 * 60 },
  breakRule: { threshold: META.break_threshold_minutes || 300, duration: META.break_duration_minutes || 30 },
  employees: new Map(),      // employees who can work this position
  shifts: new Map(),         // ALL shifts (every position) — needed for overlap checks and weekly totals
  selectedEmployeeId: null,
  selectedDay: DAYS[0],
  editingId: null,
  menuDay: null,
};

board.style.setProperty('--position-color', POSITION_COLOR);

// --- helpers -----------------------------------------------------------------

const snap = minutes => Math.round(minutes / SLOT) * SLOT;
const yFor = minutes => (minutes - state.axis.start) * PX_PER_MIN;
const minutesAtY = y => state.axis.start + y / PX_PER_MIN;
const dayWindow = day => state.hours[day] || null;
const breakMinutes = duration => {
  const { threshold, duration: breakLength } = state.breakRule;
  return threshold > 0 && breakLength > 0 && duration >= threshold ? breakLength : 0;
};
const paidMinutes = duration => duration - breakMinutes(duration);
const selectedEmployee = () => state.employees.get(state.selectedEmployeeId) || null;

function normalizeShift(raw) {
  return { ...raw, start: clockToMinutes(raw.start_time), end: clockToMinutes(raw.end_time) };
}

function shiftsFor(day) {
  return [...state.shifts.values()]
    .filter(shift => shift.position === POSITION && shift.day_of_week === day)
    .sort((a, b) => a.start - b.start || a.end - b.end);
}

function rangeLabel(start, end) {
  return `${formatTime12(start)}–${formatTime12(end)}`;
}

/** Why a shift can't sit at [start, end) on `day`, or null when it fits. */
function conflictFor(shift, day, start, end) {
  const storeWindow = dayWindow(day);
  if (!storeWindow) return `The store is closed on ${day}.`;
  if (start < storeWindow.open || end > storeWindow.close) return `Shifts must be within store hours (${rangeLabel(storeWindow.open, storeWindow.close)}).`;
  if (end - start < MINIMUM) return `Shifts must be at least ${MINIMUM} minutes.`;
  const employee = state.employees.get(shift.employee_id);
  if (employee) {
    const ranges = availabilityRanges(employee.availability, day);
    if (ranges && !ranges.some(([from, to]) => start >= from && end <= to)) {
      return ranges.length
        ? `${employee.name} is only available ${ranges.map(([from, to]) => rangeLabel(from, to)).join(', ')} on ${day}.`
        : `${employee.name} is unavailable on ${day}.`;
    }
  }
  for (const other of state.shifts.values()) {
    if (other.id === shift.id || other.employee_id !== shift.employee_id || other.day_of_week !== day) continue;
    if (start < other.end && end > other.start) return `Overlaps their ${other.position} shift ${rangeLabel(other.start, other.end)}.`;
  }
  return null;
}

/** First availability window on `day` (∩ store hours) that can hold at least a minimum shift. */
function availableWindow(employee, day) {
  const storeWindow = dayWindow(day);
  if (!storeWindow) return null;
  const ranges = availabilityRanges(employee.availability, day);
  if (ranges === null) return { ...storeWindow };
  for (const [from, to] of ranges) {
    const open = Math.max(storeWindow.open, from);
    const close = Math.min(storeWindow.close, to);
    if (close - open >= MINIMUM) return { open, close };
  }
  return null;
}

// --- rendering: axis & columns -----------------------------------------------

function computeAxis() {
  const open = DAYS.map(dayWindow).filter(Boolean);
  state.axis = open.length
    ? { start: Math.min(...open.map(w => w.open)), end: Math.max(...open.map(w => w.close)) }
    : { start: 9 * 60, end: 21 * 60 };
  boardBody.style.height = `${yFor(state.axis.end)}px`;
  // Hour lines are a repeating background; offset it so lines land on whole hours.
  boardBody.style.backgroundPositionY = `${((60 - (state.axis.start % 60)) % 60) * PX_PER_MIN}px`;

  const axis = $('#axis');
  axis.innerHTML = '';
  for (let minute = Math.ceil(state.axis.start / 60) * 60; minute <= state.axis.end; minute += 60) {
    const label = document.createElement('span');
    label.className = 'axis-label';
    label.style.top = `${yFor(minute)}px`;
    // Labels are centred on their line; pin the first and last inside the board.
    if (minute === state.axis.start) label.style.transform = 'none';
    else if (minute === state.axis.end) label.style.transform = 'translateY(-100%)';
    label.textContent = formatTimeShort(minute);
    axis.appendChild(label);
  }
}

function renderHeaders() {
  for (const day of DAYS) {
    const storeWindow = dayWindow(day);
    $(`[data-day-head="${day}"]`).classList.toggle('is-closed', !storeWindow);
    $(`[data-day-hours="${day}"]`).textContent = storeWindow ? `${formatTimeShort(storeWindow.open)}–${formatTimeShort(storeWindow.close)}` : 'Closed';
    const shifts = shiftsFor(day);
    $(`[data-day-count="${day}"]`).textContent = shifts.length ? plural(shifts.length, 'shift') : '';
    $(`[data-day-add="${day}"]`).disabled = !storeWindow || !state.selectedEmployeeId;
    $(`[data-day-tab="${day}"]`)?.classList.toggle('has-shifts', shifts.length > 0);
  }
}

function shade(container, className, from, to) {
  if (to <= from) return;
  const element = document.createElement('div');
  element.className = `shade ${className}`;
  element.style.top = `${yFor(from)}px`;
  element.style.height = `${yFor(to) - yFor(from)}px`;
  container.appendChild(element);
}

function renderLayers(day) {
  const column = $(`.day-col[data-day="${day}"]`);
  const layers = $(`[data-layers="${day}"]`);
  const storeWindow = dayWindow(day);
  layers.innerHTML = '';
  column.classList.toggle('is-closed', !storeWindow);
  column.classList.toggle('can-add', Boolean(storeWindow && state.selectedEmployeeId));
  if (!storeWindow) return;

  shade(layers, 'closed', state.axis.start, storeWindow.open);
  shade(layers, 'closed', storeWindow.close, state.axis.end);

  const employee = selectedEmployee();
  if (!employee) return;
  const ranges = availabilityRanges(employee.availability, day);
  if (ranges === null) return;
  // Shade the parts of the store day the selected person cannot work.
  let cursor = storeWindow.open;
  for (const [from, to] of [...ranges].sort((a, b) => a[0] - b[0])) {
    shade(layers, 'unavailable', cursor, Math.min(from, storeWindow.close));
    cursor = Math.max(cursor, to);
  }
  shade(layers, 'unavailable', cursor, storeWindow.close);
}

function renderCoverage(day) {
  const container = $(`[data-coverage="${day}"]`);
  container.innerHTML = '';
  const storeWindow = dayWindow(day);
  if (!storeWindow) return;
  // Headcount per slot, then merge equal runs into one segment each.
  const slots = Math.round((storeWindow.close - storeWindow.open) / SLOT);
  const counts = new Array(slots).fill(0);
  for (const shift of shiftsFor(day)) {
    const first = Math.max(0, Math.floor((shift.start - storeWindow.open) / SLOT));
    const last = Math.min(slots, Math.ceil((shift.end - storeWindow.open) / SLOT));
    for (let index = first; index < last; index += 1) counts[index] += 1;
  }
  let runStart = 0;
  for (let index = 1; index <= slots; index += 1) {
    if (index === slots || counts[index] !== counts[runStart]) {
      if (counts[runStart] > 0) {
        const segment = document.createElement('div');
        segment.className = 'cover-seg';
        segment.style.setProperty('--n', Math.min(counts[runStart] - 1, 3));
        segment.style.top = `${yFor(storeWindow.open + runStart * SLOT)}px`;
        segment.style.height = `${(index - runStart) * SLOT * PX_PER_MIN}px`;
        segment.title = `${plural(counts[runStart], 'person', 'people')} ${rangeLabel(storeWindow.open + runStart * SLOT, storeWindow.open + index * SLOT)}`;
        container.appendChild(segment);
      }
      runStart = index;
    }
  }
}

/** Assign overlapping shifts to side-by-side lanes, sized per overlap cluster. */
function layoutLanes(shifts) {
  const placement = new Map();
  let cluster = [];
  let clusterEnd = -Infinity;
  const flush = () => {
    const laneEnds = [];
    const lanes = new Map();
    for (const shift of cluster) {
      let lane = laneEnds.findIndex(end => end <= shift.start);
      if (lane === -1) { lane = laneEnds.length; laneEnds.push(0); }
      laneEnds[lane] = shift.end;
      lanes.set(shift.id, lane);
    }
    for (const shift of cluster) placement.set(shift.id, { lane: lanes.get(shift.id), lanes: laneEnds.length });
    cluster = [];
  };
  for (const shift of shifts) {
    if (shift.start >= clusterEnd && cluster.length) flush();
    cluster.push(shift);
    clusterEnd = Math.max(clusterEnd, shift.end);
  }
  if (cluster.length) flush();
  return placement;
}

function positionBlock(block, start, end, lane = 0, lanes = 1) {
  const height = (end - start) * PX_PER_MIN;
  block.style.top = `${yFor(start)}px`;
  block.style.height = `${height}px`;
  block.style.left = `calc(${(lane / lanes) * 100}% + ${lane ? 2 : 0}px)`;
  block.style.width = `calc(${100 / lanes}% - ${lanes > 1 ? 2 : 0}px)`;
  block.classList.toggle('short', height < 58);
  block.classList.toggle('tiny', height < 40);
}

function updateBlockText(block, start, end, day) {
  const duration = end - start;
  block.querySelector('.block-time').textContent = rangeLabel(start, end);
  block.querySelector('.block-paid').textContent = `${formatDuration(paidMinutes(duration))} paid${breakMinutes(duration) ? ` · ${breakMinutes(duration)}m break` : ''}`;
  block.setAttribute('aria-label', `${block.querySelector('.block-name').textContent}, ${day} ${rangeLabel(start, end)}. Press Enter to edit, arrow keys to move.`);
}

function blockElement(shift) {
  const block = document.createElement('div');
  block.className = `shift-block${shift.pending ? ' pending' : ''}${shift.id === state.editingId ? ' is-editing' : ''}`;
  block.dataset.shiftId = shift.id;
  block.tabIndex = 0;
  block.setAttribute('role', 'button');
  block.style.setProperty('--employee-color', shift.employee_color);
  block.innerHTML = `
    <div class="block-handle top" data-handle="start"></div>
    <div class="block-body">
      <strong class="block-name">${escapeHtml(shift.employee_name)}</strong>
      <span class="block-time"></span>
      <span class="block-paid"></span>
    </div>
    <div class="block-handle bottom" data-handle="end"></div>
    <div class="block-status" aria-live="polite"></div>`;
  updateBlockText(block, shift.start, shift.end, shift.day_of_week);
  return block;
}

function renderShifts(day) {
  const container = $(`[data-shifts="${day}"]`);
  const focusedId = document.activeElement?.closest?.('.shift-block')?.dataset.shiftId;
  container.innerHTML = '';
  const shifts = shiftsFor(day);
  const placement = layoutLanes(shifts);
  for (const shift of shifts) {
    const block = blockElement(shift);
    const { lane, lanes } = placement.get(shift.id);
    positionBlock(block, shift.start, shift.end, lane, lanes);
    container.appendChild(block);
    if (String(shift.id) === focusedId) block.focus({ preventScroll: true });
  }
}

function renderDay(day) {
  renderLayers(day);
  renderCoverage(day);
  renderShifts(day);
}

function renderSummary() {
  const shifts = [...state.shifts.values()].filter(shift => shift.position === POSITION);
  const scheduled = shifts.reduce((sum, shift) => sum + (shift.end - shift.start), 0);
  const paid = shifts.reduce((sum, shift) => sum + paidMinutes(shift.end - shift.start), 0);
  const people = new Set(shifts.map(shift => shift.employee_id)).size;
  $('#board-summary').textContent = shifts.length
    ? `${plural(shifts.length, 'shift')} · ${plural(people, 'person', 'people')} · ${formatDuration(scheduled)} scheduled · ${formatDuration(paid)} paid`
    : 'No shifts yet — select someone in the roster and click a day to begin.';
}

function renderAll() {
  renderHeaders();
  for (const day of DAYS) renderDay(day);
  renderSummary();
  renderRoster();
}

// --- roster -----------------------------------------------------------------

function weeklyPaidMinutes(employeeId) {
  return [...state.shifts.values()]
    .filter(shift => shift.employee_id === employeeId)
    .reduce((sum, shift) => sum + paidMinutes(shift.end - shift.start), 0);
}

function renderRoster() {
  const roster = $('#roster');
  const employees = [...state.employees.values()];
  if (!employees.length) {
    roster.innerHTML = `<p class="roster-empty">Nobody can work ${escapeHtml(POSITION)} yet. <a href="/employees">Add the position to an employee.</a></p>`;
    $('#roster-hint').textContent = '';
    return;
  }
  roster.innerHTML = employees.map(employee => {
    const minutes = weeklyPaidMinutes(employee.id);
    const selected = employee.id === state.selectedEmployeeId;
    return `
      <button type="button" class="roster-item" role="option" data-employee="${employee.id}" aria-selected="${selected}" style="--employee-color:${escapeHtml(employee.color)}">
        <span class="dot"></span>
        <span>
          <span class="roster-name">${escapeHtml(employee.name)}</span>
          <span class="roster-meta">${escapeHtml(employee.employment_type)} · ${escapeHtml(availabilityText(employee.availability))}</span>
        </span>
        <span class="roster-hours${minutes > WEEKLY_HOURS_WARNING ? ' over' : ''}" title="Paid hours this week across all positions">${formatDuration(minutes)}</span>
      </button>`;
  }).join('');
  const employee = selectedEmployee();
  $('#roster-hint').textContent = employee
    ? `Click a day column to place ${employee.name}, or drag to draw the shift.`
    : 'Select a person, then click a day to place a shift.';
}

$('#roster').addEventListener('click', event => {
  const item = event.target.closest('[data-employee]');
  if (!item) return;
  const id = Number(item.dataset.employee);
  state.selectedEmployeeId = state.selectedEmployeeId === id ? null : id;
  renderAll();
});

// --- creating shifts ---------------------------------------------------------

async function createShift(employee, day, start, end) {
  const temp = { id: `new-${Date.now()}`, employee_id: employee.id, employee_name: employee.name, employee_color: employee.color, position: POSITION, day_of_week: day, start, end, pending: true };
  const conflict = conflictFor(temp, day, start, end);
  if (conflict) { showError(conflict); return; }
  state.shifts.set(temp.id, temp);
  renderDay(day);
  const { ok, data } = await api.post('/api/shifts', { employee_id: employee.id, position: POSITION, day_of_week: day, start_time: minutesToClock(start), end_time: minutesToClock(end) });
  state.shifts.delete(temp.id);
  if (!ok) { renderDay(day); showError(data.error || 'Unable to save shift'); return; }
  state.shifts.set(data.id, normalizeShift(data));
  renderHeaders();
  renderDay(day);
  renderSummary();
  renderRoster();
}

$('.board-header').addEventListener('click', event => {
  const button = event.target.closest('[data-day-add]');
  if (!button) return;
  const employee = selectedEmployee();
  if (!employee) { showError('Select a person in the roster first.'); return; }
  const day = button.dataset.dayAdd;
  const available = availableWindow(employee, day);
  if (!available) { showError(`${employee.name} is not available on ${day} during store hours.`); return; }
  createShift(employee, day, available.open, Math.min(available.close, available.open + DEFAULT_ADD_MINUTES));
});

// --- pointer interactions ----------------------------------------------------

function dayAtPoint(x) {
  if (singleDayQuery.matches) return null;
  for (const column of $$('.day-col')) {
    const rect = column.getBoundingClientRect();
    if (x >= rect.left && x <= rect.right) return column.dataset.day;
  }
  return null;
}

boardBody.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  const block = event.target.closest('.shift-block');
  if (block) { startBlockDrag(event, block); return; }
  const column = event.target.closest('.day-col');
  if (column) startDraw(event, column);
});

function startBlockDrag(event, block) {
  const shift = state.shifts.get(Number(block.dataset.shiftId));
  if (!shift || shift.pending) return;
  event.preventDefault();
  closeEditor();
  const handle = event.target.closest('[data-handle]')?.dataset.handle || null;
  const origin = { y: event.clientY, start: shift.start, end: shift.end };
  const current = { day: shift.day_of_week, start: shift.start, end: shift.end };
  let moved = false;
  block.setPointerCapture(event.pointerId);

  const onMove = moveEvent => {
    const dy = moveEvent.clientY - origin.y;
    if (Math.abs(dy) > 3) moved = true;
    const delta = snap(dy / PX_PER_MIN);
    if (handle === 'start') {
      const storeWindow = dayWindow(current.day);
      current.start = clamp(origin.start + delta, storeWindow.open, current.end - MINIMUM);
    } else if (handle === 'end') {
      const storeWindow = dayWindow(current.day);
      current.end = clamp(origin.end + delta, current.start + MINIMUM, storeWindow.close);
    } else {
      const targetDay = dayAtPoint(moveEvent.clientX);
      if (targetDay && targetDay !== current.day && dayWindow(targetDay)) {
        current.day = targetDay;
        moved = true;
        $(`[data-shifts="${targetDay}"]`).appendChild(block);
        $$('.day-col').forEach(column => column.classList.toggle('is-target', column.dataset.day === targetDay));
      }
      const storeWindow = dayWindow(current.day);
      const duration = origin.end - origin.start;
      current.start = clamp(origin.start + delta, storeWindow.open, storeWindow.close - duration);
      current.end = current.start + duration;
    }
    if (!moved) return;
    block.classList.add('dragging');
    positionBlock(block, current.start, current.end);
    updateBlockText(block, current.start, current.end, current.day);
    block.classList.toggle('invalid', Boolean(conflictFor(shift, current.day, current.start, current.end)));
  };

  const onUp = () => {
    block.removeEventListener('pointermove', onMove);
    block.removeEventListener('pointerup', onUp);
    block.removeEventListener('pointercancel', onUp);
    block.classList.remove('dragging', 'invalid');
    $$('.day-col.is-target').forEach(column => column.classList.remove('is-target'));
    if (!moved) { openEditor(shift); return; }
    if (current.day === shift.day_of_week && current.start === shift.start && current.end === shift.end) { renderDay(shift.day_of_week); return; }
    commitShift(shift, current.day, current.start, current.end);
  };

  block.addEventListener('pointermove', onMove);
  block.addEventListener('pointerup', onUp);
  block.addEventListener('pointercancel', onUp);
}

function startDraw(event, column) {
  const day = column.dataset.day;
  const storeWindow = dayWindow(day);
  const employee = selectedEmployee();
  if (!storeWindow) return;
  event.preventDefault();
  closeEditor();
  const rect = column.getBoundingClientRect();
  const anchor = clamp(snap(minutesAtY(event.clientY - rect.top)), storeWindow.open, storeWindow.close - SLOT);
  let current = { start: anchor, end: anchor + SLOT };
  let moved = false;
  let ghost = null;
  column.setPointerCapture(event.pointerId);

  const onMove = moveEvent => {
    if (!employee) return;
    if (Math.abs(moveEvent.clientY - event.clientY) > 4) moved = true;
    if (!moved) return;
    const minutes = clamp(snap(minutesAtY(moveEvent.clientY - rect.top)), storeWindow.open, storeWindow.close);
    current = minutes >= anchor
      ? { start: anchor, end: Math.min(Math.max(minutes, anchor + MINIMUM), storeWindow.close) }
      : { start: Math.max(Math.min(minutes, anchor - MINIMUM), storeWindow.open), end: anchor };
    if (!ghost) {
      ghost = document.createElement('div');
      ghost.className = 'draw-ghost';
      ghost.innerHTML = '<span></span>';
      $(`[data-shifts="${day}"]`).appendChild(ghost);
    }
    ghost.style.top = `${yFor(current.start)}px`;
    ghost.style.height = `${(current.end - current.start) * PX_PER_MIN}px`;
    ghost.querySelector('span').textContent = rangeLabel(current.start, current.end);
  };

  const onUp = () => {
    column.removeEventListener('pointermove', onMove);
    column.removeEventListener('pointerup', onUp);
    column.removeEventListener('pointercancel', onUp);
    ghost?.remove();
    if (!employee) { showError('Select a person in the roster first, then click a day.'); return; }
    if (moved) { createShift(employee, day, current.start, current.end); return; }
    // Plain click: a default-length shift starting at the clicked time, kept inside availability.
    const ranges = availabilityRanges(employee.availability, day);
    const range = ranges === null ? [storeWindow.open, storeWindow.close] : ranges.find(([from, to]) => anchor >= from && anchor < to);
    if (!range) { showError(`${employee.name} is not available at ${formatTime12(anchor)} on ${day}.`); return; }
    const end = Math.min(anchor + DEFAULT_CLICK_MINUTES, range[1], storeWindow.close);
    if (end - anchor < MINIMUM) { showError(`Not enough room for a shift starting at ${formatTime12(anchor)}.`); return; }
    createShift(employee, day, anchor, end);
  };

  column.addEventListener('pointermove', onMove);
  column.addEventListener('pointerup', onUp);
  column.addEventListener('pointercancel', onUp);
}

// --- saving & removing -------------------------------------------------------

function flashBlockError(shiftId, message) {
  const block = $(`.shift-block[data-shift-id="${shiftId}"]`);
  if (!block) return;
  block.querySelector('.block-status').textContent = message;
  block.classList.add('has-error');
  window.setTimeout(() => block.classList.remove('has-error'), 3500);
}

async function commitShift(shift, day, start, end) {
  const previousDay = shift.day_of_week;
  const conflict = conflictFor(shift, day, start, end);
  if (conflict) {
    renderDay(previousDay);
    if (day !== previousDay) renderDay(day);
    flashBlockError(shift.id, conflict);
    return false;
  }
  $(`.shift-block[data-shift-id="${shift.id}"]`)?.classList.add('saving');
  const { ok, data } = await api.put(`/api/shifts/${shift.id}`, {
    employee_id: shift.employee_id, position: POSITION, day_of_week: day,
    start_time: minutesToClock(start), end_time: minutesToClock(end),
  });
  if (!ok) {
    renderDay(previousDay);
    if (day !== previousDay) renderDay(day);
    flashBlockError(shift.id, data.error || 'Not saved');
    showError(data.error || 'Unable to save shift');
    return false;
  }
  state.shifts.set(data.id, normalizeShift(data));
  renderHeaders();
  renderDay(previousDay);
  if (day !== previousDay) renderDay(day);
  renderSummary();
  renderRoster();
  return true;
}

function refreshAfterChange(...days) {
  renderHeaders();
  for (const day of new Set(days)) renderDay(day);
  renderSummary();
  renderRoster();
}

/** Remove immediately; the toast offers Undo, which re-creates the shift. */
async function removeShift(shift) {
  const { ok, status, data } = await api.delete(`/api/shifts/${shift.id}`);
  if (!ok && status !== 404) { showError(data.error || 'Unable to remove shift'); return; }
  state.shifts.delete(shift.id);
  closeEditor();
  refreshAfterChange(shift.day_of_week);
  showToast(`Removed ${shift.employee_name}, ${shift.day_of_week.slice(0, 3)} ${rangeLabel(shift.start, shift.end)}`, {
    duration: UNDO_WINDOW_MS,
    action: {
      label: 'Undo',
      onClick: async () => {
        const restored = await api.post('/api/shifts', {
          employee_id: shift.employee_id, position: shift.position, day_of_week: shift.day_of_week,
          start_time: minutesToClock(shift.start), end_time: minutesToClock(shift.end),
        });
        if (!restored.ok) { showError(restored.data.error || 'Unable to restore the shift'); return; }
        state.shifts.set(restored.data.id, normalizeShift(restored.data));
        refreshAfterChange(shift.day_of_week);
        showToast('Shift restored');
      },
    },
  });
}

/** Re-fetch every shift after a bulk change (copy, clear) so the board matches the server. */
async function reloadShifts() {
  const { ok, data } = await api.get('/api/shifts');
  if (!ok) { showError(data.error || 'Unable to refresh shifts'); return; }
  state.shifts = new Map(data.map(shift => [shift.id, normalizeShift(shift)]));
  renderAll();
}

function dayCheckboxes(container, excludeDay) {
  container.innerHTML = DAYS.filter(day => day !== excludeDay).map(day => `
    <label class="check"><input type="checkbox" value="${day}" ${dayWindow(day) ? '' : 'disabled'}> ${day.slice(0, 3)}</label>`).join('');
}

function checkedDays(container) {
  return $$('input:checked', container).map(input => input.value);
}

function describeCopy(result, targets) {
  const days = targets.map(day => day.slice(0, 3)).join(', ');
  const parts = [];
  if (result.created.length) parts.push(`Copied ${plural(result.created.length, 'shift')} to ${days}`);
  if (result.removed) parts.push(`${plural(result.removed, 'existing shift')} replaced`);
  if (result.skipped.length) parts.push(`${plural(result.skipped.length, 'shift')} skipped: ${result.skipped[0].reason}`);
  return parts.join(' · ');
}

async function copyShifts(sourceDay, targets, { shiftIds = null, replace = false } = {}) {
  if (!targets.length) { showError('Choose at least one day.'); return false; }
  const { ok, data } = await api.post('/api/shifts/copy', {
    position: POSITION, source_day: sourceDay, target_days: targets, shift_ids: shiftIds, replace,
  });
  if (!ok) { showError(data.error || 'Unable to copy shifts'); return false; }
  await reloadShifts();
  showToast(describeCopy(data, targets), { type: data.created.length ? 'info' : 'error', duration: 6000 });
  return true;
}

// --- editor popover ----------------------------------------------------------

function openEditor(shift) {
  state.editingId = shift.id;
  $$('.shift-block').forEach(block => block.classList.toggle('is-editing', Number(block.dataset.shiftId) === shift.id));
  editor.querySelector('[data-editor-dot]').style.setProperty('--dot-color', shift.employee_color);
  editor.querySelector('[data-editor-name]').textContent = shift.employee_name;
  editor.querySelector('[data-editor-day]').value = shift.day_of_week;
  editor.querySelector('[data-editor-start]').value = minutesToClock(shift.start);
  editor.querySelector('[data-editor-end]').value = minutesToClock(shift.end);
  editor.querySelector('[data-editor-error]').hidden = true;
  dayCheckboxes(editor.querySelector('[data-editor-targets]'), shift.day_of_week);
  editor.querySelector('.editor-duplicate').open = false;
  editor.hidden = false;
  updateEditorMeta();

  // Place beside the block, staying inside the viewport; CSS turns it into a bottom sheet on phones.
  const block = $(`.shift-block[data-shift-id="${shift.id}"]`);
  if (block && !singleDayQuery.matches) {
    const rect = block.getBoundingClientRect();
    const width = editor.offsetWidth;
    const height = editor.offsetHeight;
    let left = rect.right + 10;
    if (left + width > window.innerWidth - 12) left = rect.left - width - 10;
    if (left < 12) left = 12;
    editor.style.left = `${left}px`;
    editor.style.top = `${clamp(rect.top, 12, window.innerHeight - height - 12)}px`;
  }
  editor.querySelector('[data-editor-start]').focus();
}

function closeEditor() {
  if (editor.hidden) return;
  editor.hidden = true;
  const previous = state.editingId;
  state.editingId = null;
  $(`.shift-block[data-shift-id="${previous}"]`)?.classList.remove('is-editing');
}

function editorValues() {
  return {
    day: editor.querySelector('[data-editor-day]').value,
    start: clockToMinutes(editor.querySelector('[data-editor-start]').value || '00:00'),
    end: clockToMinutes(editor.querySelector('[data-editor-end]').value || '00:00'),
  };
}

function updateEditorMeta() {
  const shift = state.shifts.get(state.editingId);
  if (!shift) return;
  const { day, start, end } = editorValues();
  const duration = end - start;
  const meta = editor.querySelector('[data-editor-meta]');
  const error = editor.querySelector('[data-editor-error]');
  if (duration <= 0) { meta.textContent = ''; error.textContent = 'End must be after start.'; error.hidden = false; return; }
  const conflict = conflictFor(shift, day, start, end);
  error.hidden = !conflict;
  error.textContent = conflict || '';
  meta.textContent = `${formatDuration(duration)} scheduled · ${formatDuration(paidMinutes(duration))} paid${breakMinutes(duration) ? ` · ${breakMinutes(duration)}m break` : ''}`;
}

editor.addEventListener('input', updateEditorMeta);
editor.addEventListener('change', updateEditorMeta);
editor.querySelector('[data-editor-close]').addEventListener('click', closeEditor);
editor.querySelector('[data-editor-remove]').addEventListener('click', () => {
  const shift = state.shifts.get(state.editingId);
  if (shift) removeShift(shift);
});
editor.querySelector('[data-editor-save]').addEventListener('click', async event => {
  const shift = state.shifts.get(state.editingId);
  if (!shift) return;
  const { day, start, end } = editorValues();
  if (end <= start) { updateEditorMeta(); return; }
  const button = event.currentTarget;
  button.disabled = true;
  const saved = await commitShift(shift, day, start, end);
  button.disabled = false;
  if (saved) closeEditor();
  else updateEditorMeta();
});
editor.querySelector('[data-editor-duplicate]').addEventListener('click', async event => {
  const shift = state.shifts.get(state.editingId);
  if (!shift) return;
  const button = event.currentTarget;
  button.disabled = true;
  const done = await copyShifts(shift.day_of_week, checkedDays(editor.querySelector('[data-editor-targets]')), { shiftIds: [shift.id] });
  button.disabled = false;
  if (done) closeEditor();
});
editor.addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); closeEditor(); }
  if (event.key === 'Enter' && event.target.tagName !== 'BUTTON') { event.preventDefault(); editor.querySelector('[data-editor-save]').click(); }
});
document.addEventListener('pointerdown', event => {
  if (!editor.hidden && !editor.contains(event.target) && !event.target.closest('.shift-block')) closeEditor();
});

// --- day menu: copy / clear --------------------------------------------------

function openDayMenu(day, anchor) {
  closeEditor();
  state.menuDay = day;
  const count = shiftsFor(day).length;
  dayMenu.querySelector('[data-menu-title]').textContent = `${day} · ${plural(count, 'shift')}`;
  dayCheckboxes(dayMenu.querySelector('[data-menu-targets]'), day);
  dayMenu.querySelector('[data-menu-replace]').checked = false;
  dayMenu.querySelector('[data-menu-copy]').disabled = count === 0;
  dayMenu.querySelector('[data-menu-clear]').disabled = count === 0;
  dayMenu.hidden = false;
  if (!singleDayQuery.matches) {
    const rect = anchor.getBoundingClientRect();
    const width = dayMenu.offsetWidth;
    dayMenu.style.left = `${clamp(rect.right - width, 12, window.innerWidth - width - 12)}px`;
    dayMenu.style.top = `${rect.bottom + 8}px`;
  }
  dayMenu.querySelector('[data-menu-targets] input:not(:disabled)')?.focus();
}

function closeDayMenu() {
  dayMenu.hidden = true;
  state.menuDay = null;
}

$('.board-header').addEventListener('click', event => {
  const button = event.target.closest('[data-day-menu]');
  if (!button) return;
  if (state.menuDay === button.dataset.dayMenu) closeDayMenu();
  else openDayMenu(button.dataset.dayMenu, button);
});
dayMenu.querySelector('[data-menu-close]').addEventListener('click', closeDayMenu);
dayMenu.querySelector('[data-menu-copy]').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  const done = await copyShifts(state.menuDay, checkedDays(dayMenu.querySelector('[data-menu-targets]')), {
    replace: dayMenu.querySelector('[data-menu-replace]').checked,
  });
  button.disabled = false;
  if (done) closeDayMenu();
});
dayMenu.querySelector('[data-menu-clear]').addEventListener('click', async () => {
  const day = state.menuDay;
  const count = shiftsFor(day).length;
  const confirmed = await confirmDialog({
    title: `Clear ${day}?`,
    message: `Removes ${plural(count, 'shift')} from the ${POSITION} schedule on ${day}. Other positions are not affected.`,
    confirmLabel: 'Clear day',
    danger: true,
  });
  if (!confirmed) return;
  const { ok, data } = await api.delete(`/api/shifts?position=${encodeURIComponent(POSITION)}&day=${encodeURIComponent(day)}`);
  if (!ok) { showError(data.error || 'Unable to clear the day'); return; }
  closeDayMenu();
  await reloadShifts();
  showToast(`${plural(data.deleted_count, 'shift')} cleared from ${day}`);
});
dayMenu.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); closeDayMenu(); } });
document.addEventListener('pointerdown', event => {
  if (!dayMenu.hidden && !dayMenu.contains(event.target) && !event.target.closest('[data-day-menu]')) closeDayMenu();
});

// --- keyboard on blocks ------------------------------------------------------

const keyboardTimers = new Map();

boardBody.addEventListener('keydown', event => {
  const block = event.target.closest('.shift-block');
  if (!block) return;
  const shift = state.shifts.get(Number(block.dataset.shiftId));
  if (!shift) return;

  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openEditor(shift); return; }
  if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); removeShift(shift); return; }
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
  event.preventDefault();

  const delta = event.key === 'ArrowUp' ? -SLOT : SLOT;
  const storeWindow = dayWindow(shift.day_of_week);
  const pending = keyboardTimers.get(shift.id)?.proposed || { start: shift.start, end: shift.end };
  let { start, end } = pending;
  if (event.shiftKey) {
    end = clamp(end + delta, start + MINIMUM, storeWindow.close);
  } else {
    const duration = end - start;
    start = clamp(start + delta, storeWindow.open, storeWindow.close - duration);
    end = start + duration;
  }
  positionBlock(block, start, end);
  updateBlockText(block, start, end, shift.day_of_week);
  block.classList.toggle('invalid', Boolean(conflictFor(shift, shift.day_of_week, start, end)));

  clearTimeout(keyboardTimers.get(shift.id)?.timer);
  keyboardTimers.set(shift.id, {
    proposed: { start, end },
    timer: window.setTimeout(() => {
      keyboardTimers.delete(shift.id);
      block.classList.remove('invalid');
      commitShift(shift, shift.day_of_week, start, end);
    }, 450),
  });
});

// --- mobile: one day at a time ----------------------------------------------

function applySingleDayMode() {
  board.classList.toggle('single-day', singleDayQuery.matches);
  for (const day of DAYS) {
    const selected = day === state.selectedDay;
    $(`[data-day-head="${day}"]`).classList.toggle('is-selected', selected);
    $(`.day-col[data-day="${day}"]`).classList.toggle('is-selected', selected);
    const tab = $(`[data-day-tab="${day}"]`);
    tab.classList.toggle('active', selected);
    tab.setAttribute('aria-selected', String(selected));
  }
}

$('#day-tabs').addEventListener('click', event => {
  const tab = event.target.closest('[data-day-tab]');
  if (!tab) return;
  state.selectedDay = tab.dataset.dayTab;
  applySingleDayMode();
});
singleDayQuery.addEventListener('change', () => { closeEditor(); closeDayMenu(); applySingleDayMode(); });

// --- boot --------------------------------------------------------------------

async function load() {
  const [hours, employees, shifts] = await Promise.all([
    api.get('/api/settings'),
    api.get(`/api/employees?position=${encodeURIComponent(POSITION)}`),
    api.get('/api/shifts'),
  ]);
  for (const response of [hours, employees, shifts]) {
    if (!response.ok) throw new Error(response.data.error || 'Unable to load the schedule');
  }
  const operatingHours = hours.data.operating_hours || {};
  state.hours = Object.fromEntries(DAYS.map(day => {
    const value = operatingHours[day];
    return [day, value ? { open: clockToMinutes(value.open), close: clockToMinutes(value.close) } : null];
  }));
  state.breakRule = {
    threshold: hours.data.break_threshold_minutes ?? state.breakRule.threshold,
    duration: hours.data.break_duration_minutes ?? state.breakRule.duration,
  };
  state.employees = new Map(employees.data.map(employee => [employee.id, employee]));
  state.shifts = new Map(shifts.data.map(shift => [shift.id, normalizeShift(shift)]));
  state.selectedDay = DAYS.find(day => shiftsFor(day).length) || DAYS.find(day => dayWindow(day)) || DAYS[0];

  computeAxis();
  applySingleDayMode();
  renderAll();
}

load().catch(error => {
  $('#board-summary').textContent = error.message;
  showError(error.message);
});
