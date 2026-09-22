/** Clock arithmetic and availability parsing. All internal times are minutes since midnight. */

import { DAYS } from './dom.js';

const RANGE_RE = /^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$/;
const OPEN_RE = /^open$/i;
const UNAVAILABLE_RE = /^(unavailable|closed|none|off)$/i;

export function clockToMinutes(value) {
  const [hours, minutes] = String(value).split(':').map(Number);
  return hours * 60 + minutes;
}

export function minutesToClock(minutes) {
  const total = Math.round(minutes);
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

export function formatTime12(minutes) {
  const total = Math.round(minutes) % (24 * 60);
  const hour = Math.floor(total / 60);
  const minute = total % 60;
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour >= 12 ? 'PM' : 'AM'}`;
}

/** Compact form for tight spaces: "9a", "1:30p". */
export function formatTimeShort(minutes) {
  const total = Math.round(minutes) % (24 * 60);
  const hour = Math.floor(total / 60);
  const minute = total % 60;
  return `${hour % 12 || 12}${minute ? `:${String(minute).padStart(2, '0')}` : ''}${hour >= 12 ? 'p' : 'a'}`;
}

export function formatDuration(minutes) {
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

/**
 * Availability for one day:
 *   null              -> fully open
 *   []                -> unavailable all day
 *   [[start, end]...] -> restricted to these windows
 */
export function availabilityRanges(availability, day) {
  if (!availability || typeof availability !== 'object') return null;
  const value = availability[day];
  if (value == null || value === '' || (typeof value === 'string' && OPEN_RE.test(value))) return null;
  if (typeof value === 'string' && UNAVAILABLE_RE.test(value)) return [];
  const ranges = [];
  for (const item of Array.isArray(value) ? value : [value]) {
    const text = typeof item === 'string' ? item : `${item?.start}-${item?.end}`;
    const match = RANGE_RE.exec(text);
    if (match) ranges.push([clockToMinutes(match[1]), clockToMinutes(match[2])]);
  }
  return ranges;
}

/** Human summary: "Mon 9:00 AM–1:00 PM · Sun unavailable", or "Open". */
export function availabilityText(availability) {
  if (!availability || typeof availability !== 'object') return availability || 'Open';
  return DAYS
    .map(day => {
      const ranges = availabilityRanges(availability, day);
      if (ranges === null) return null;
      const label = day.slice(0, 3);
      if (!ranges.length) return `${label} unavailable`;
      return `${label} ${ranges.map(([start, end]) => `${formatTime12(start)}–${formatTime12(end)}`).join(', ')}`;
    })
    .filter(Boolean)
    .join(' · ') || 'Open';
}
