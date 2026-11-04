// Pure geometry for the hero field: a loose grid of points (records) that swirl into orbit around the pointer.
// No DOM access, so it is easy to test.

export const SPACING = 30; // px between grid points before jitter
export const RADIUS = 190; // px around the pointer that the field reacts within

// Deterministic 0..1 hash of two integers, so the jitter is the same on every load and every resize.
function hash(a, b) {
  let h = Math.imul(a, 374761393) + Math.imul(b, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

// A grid with a little jitter, so it reads as a field of records and not as graph paper.
export function buildPoints(width, height, spacing = SPACING) {
  const points = [];
  const cols = Math.ceil(width / spacing) + 1;
  const rows = Math.ceil(height / spacing) + 1;
  for (let row = 0; row <= rows; row += 1) {
    for (let col = 0; col <= cols; col += 1) {
      const hx = col * spacing + (hash(col, row) - 0.5) * spacing * 0.7;
      const hy = row * spacing + (hash(row + 7, col + 3) - 0.5) * spacing * 0.7;
      points.push({ hx, hy, x: hx, y: hy, glow: 0, size: 0.7 + hash(col + 11, row + 5) * 0.9 });
    }
  }
  return points;
}

// Where a point wants to be: its home, or (near the pointer) turned a little around the pointer and drawn inward,
// so nearby points look like they are falling into orbit. `pull` is 0 far away and 1 at the pointer. Points never
// end up inside `clear` px of the pointer, which keeps the drawn orbit ring empty like the logo.
export function targetFor(point, pointer, radius = RADIUS, clear = 0) {
  if (!pointer) return { x: point.hx, y: point.hy, pull: 0 };
  const dx = point.hx - pointer.x;
  const dy = point.hy - pointer.y;
  const distance = Math.hypot(dx, dy);
  if (distance === 0 || distance >= radius) return { x: point.hx, y: point.hy, pull: 0 };
  const t = 1 - distance / radius;
  const pull = t * t * (3 - 2 * t); // smoothstep
  const turn = pull * 0.55; // radians
  const drawn = distance * (1 - pull * 0.2);
  const reach = drawn < clear ? clear + drawn * 0.35 : drawn;
  const angle = Math.atan2(dy, dx) + turn;
  return {
    x: pointer.x + Math.cos(angle) * reach,
    y: pointer.y + Math.sin(angle) * reach,
    pull,
  };
}

// The few points closest to the pointer, nearest first: the records the "agent" reaches for.
export function nearest(points, pointer, radius, count, minDistance = 0) {
  if (!pointer) return [];
  return points
    .map((point) => ({ point, distance: Math.hypot(point.x - pointer.x, point.y - pointer.y) }))
    .filter((entry) => entry.distance < radius && entry.distance > minDistance)
    .sort((a, b) => a.distance - b.distance)
    .slice(0, count);
}
