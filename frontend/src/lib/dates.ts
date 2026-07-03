// Backend timestamps are ISO strings WITHOUT a timezone designator (SQLite has
// no native timezone type, so a tz-aware Python datetime round-trips through
// it as naive — e.g. "2026-07-03T11:38:52.675198", no trailing "Z"/offset).
// They are always UTC in practice. `new Date(...)` on a date-TIME string
// missing a zone offset is parsed as LOCAL time per the ECMAScript spec, so
// consuming these strings directly silently shifts every timestamp by the
// viewer's UTC offset — a multi-hour "how long has this been running" bug for
// anyone not in UTC. Normalize once, here, before handing to `Date`.
export function parseServerDate(iso: string): Date {
  const hasZone = /Z$|[+-]\d{2}:\d{2}$/.test(iso)
  return new Date(hasZone ? iso : `${iso}Z`)
}
