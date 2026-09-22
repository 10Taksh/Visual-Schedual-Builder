/**
 * Per-day availability editor. Replaces the raw JSON textarea.
 *
 *   const editor = createAvailabilityEditor(container);
 *   editor.setValue(employee.availability);       // "Open" or canonical dict
 *   const { value, error } = editor.getValue();   // canonical form, or an error message
 */

import { DAYS, escapeHtml } from './dom.js';
import { availabilityRanges, minutesToClock } from './time.js';

const MODES = [
  ['open', 'Open'],
  ['unavailable', 'Unavailable'],
  ['custom', 'Custom hours'],
];

function rangeRow(start = '09:00', end = '17:00') {
  return `
    <div class="avail-range">
      <input type="time" data-start value="${escapeHtml(start)}" step="900" aria-label="From">
      <span class="avail-dash">–</span>
      <input type="time" data-end value="${escapeHtml(end)}" step="900" aria-label="To">
      <button type="button" class="avail-remove" data-remove-range aria-label="Remove this time range">×</button>
    </div>`;
}

export function createAvailabilityEditor(container) {
  container.classList.add('avail-editor');
  container.innerHTML = DAYS.map(day => `
    <div class="avail-row" data-day="${day}">
      <span class="avail-day">${day.slice(0, 3)}</span>
      <select class="avail-mode" data-mode aria-label="${day} availability">
        ${MODES.map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}
      </select>
      <div class="avail-ranges" data-ranges hidden>
        <button type="button" class="avail-add" data-add-range>+ Add hours</button>
      </div>
    </div>`).join('');

  const rows = Object.fromEntries([...container.querySelectorAll('.avail-row')].map(row => [row.dataset.day, row]));

  function addRange(row, start, end) {
    const ranges = row.querySelector('[data-ranges]');
    ranges.insertAdjacentHTML('beforeend', rangeRow(start, end));
    // Keep the add button last.
    ranges.appendChild(ranges.querySelector('[data-add-range]'));
  }

  function setMode(row, mode) {
    row.querySelector('[data-mode]').value = mode;
    const ranges = row.querySelector('[data-ranges]');
    ranges.hidden = mode !== 'custom';
    row.classList.toggle('is-custom', mode === 'custom');
    row.classList.toggle('is-unavailable', mode === 'unavailable');
    if (mode === 'custom' && !ranges.querySelector('.avail-range')) addRange(row);
  }

  container.addEventListener('change', event => {
    if (event.target.matches('[data-mode]')) setMode(event.target.closest('.avail-row'), event.target.value);
  });
  container.addEventListener('click', event => {
    const row = event.target.closest('.avail-row');
    if (!row) return;
    if (event.target.closest('[data-add-range]')) {
      addRange(row);
      row.querySelector('.avail-range:last-of-type [data-start]').focus();
    } else if (event.target.closest('[data-remove-range]')) {
      event.target.closest('.avail-range').remove();
      if (!row.querySelector('.avail-range')) setMode(row, 'open');
    }
  });

  function setValue(availability) {
    for (const day of DAYS) {
      const row = rows[day];
      row.querySelectorAll('.avail-range').forEach(range => range.remove());
      const ranges = availabilityRanges(availability, day);
      if (ranges === null) {
        setMode(row, 'open');
      } else if (!ranges.length) {
        setMode(row, 'unavailable');
      } else {
        for (const [start, end] of ranges) addRange(row, minutesToClock(start), minutesToClock(end));
        setMode(row, 'custom');
      }
    }
  }

  function getValue() {
    const result = {};
    for (const day of DAYS) {
      const row = rows[day];
      const mode = row.querySelector('[data-mode]').value;
      row.classList.remove('has-error');
      if (mode === 'open') continue;
      if (mode === 'unavailable') { result[day] = 'Unavailable'; continue; }
      const ranges = [];
      for (const range of row.querySelectorAll('.avail-range')) {
        const start = range.querySelector('[data-start]').value;
        const end = range.querySelector('[data-end]').value;
        if (!start || !end || end <= start) {
          row.classList.add('has-error');
          return { value: null, error: `${day}: enter a start time that is before the end time.` };
        }
        ranges.push(`${start}-${end}`);
      }
      if (ranges.length) result[day] = ranges;
    }
    return { value: Object.keys(result).length ? result : 'Open', error: null };
  }

  setValue('Open');
  return { setValue, getValue };
}
