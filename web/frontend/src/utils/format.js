export function fmtDate(raw) {
  const s = String(raw || '').replace(/\D/g, '')
  if (s.length === 8) return `${s.slice(0,4)}.${s.slice(4,6)}.${s.slice(6,8)}`
  return raw || ''
}

export function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function stripHtml(str) {
  return String(str || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .trim()
}

export function fmtScheduleInterval(interval, day, time) {
  const t = time ? ` ${time}` : ''
  if (interval === 'daily')   return `매일${t}`
  if (interval === 'weekly')  return day ? `매주 ${day}요일${t}` : `매주${t}`
  if (interval === 'monthly') return day ? `매월 ${day}일${t}` : `매월${t}`
  return interval
}
