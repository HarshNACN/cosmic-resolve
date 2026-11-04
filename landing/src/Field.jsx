import { useEffect, useRef } from "react";
import { RADIUS, buildPoints, nearest, targetFor } from "./field.js";

const LERP = 0.14; // spring speed toward the target position
const LINKS = 7; // lines drawn from the pointer to the nearest points
const SETTLED = 0.05; // px; below this a point counts as still

// Colors match the brand and the workbench trace, where teal marks tool calls.
const MUTED = "170, 177, 198";
const TEAL = "79, 184, 204";
const VIOLET = "143, 45, 224";
// Orbit size: the ring drawn around the focus (the brand mark at hero scale) and how far the field reacts around it.
export function orbitSize(width) {
  return width >= 860 ? { ring: 70, reach: 250 } : { ring: 44, reach: RADIUS };
}
const SATELLITE_ANGLE = -0.7; // radians; matches the satellite's place on the logo

// The orbit's resting place: the empty right side of the hero on wide screens, above the headline on narrow ones.
export function restingFocus(width, height) {
  return width >= 860 ? { x: width * 0.76, y: height * 0.47 } : { x: width * 0.72, y: height * 0.17 };
}

const reducedMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

// Full-bleed canvas behind the hero. It only animates while the pointer is moving or the points are still settling,
// so an idle page uses no CPU. At rest the orbit sits at restingFocus, which is also the whole picture for touch input
// and reduced motion.
export default function Field() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext?.("2d");
    if (!ctx) return undefined; // no canvas support (for example jsdom in tests)

    let points = [];
    let pointer = null;
    let anchor = null; // where the orbit rests when no pointer is over the field
    let ring = 44;
    let reach = RADIUS;
    let frame = 0;
    let width = 0;
    let height = 0;

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      const still = reducedMotion();
      const focus = still ? anchor : pointer ?? anchor;
      const ease = still ? 1 : LERP; // reduced motion: jump straight to the finished picture
      let moving = false;

      for (const point of points) {
        const target = targetFor(point, focus, reach, ring + 10);
        const nx = point.x + (target.x - point.x) * ease;
        const ny = point.y + (target.y - point.y) * ease;
        if (Math.abs(nx - point.x) > SETTLED || Math.abs(ny - point.y) > SETTLED) moving = true;
        point.x = nx;
        point.y = ny;
        point.glow += (target.pull - point.glow) * ease;

        const lit = point.glow > 0.02;
        ctx.fillStyle = lit ? `rgba(${TEAL}, ${0.35 + point.glow * 0.65})` : `rgba(${MUTED}, 0.3)`;
        ctx.beginPath();
        ctx.arc(point.x, point.y, point.size + point.glow * 2, 0, Math.PI * 2);
        ctx.fill();
      }

      if (focus) {
        ctx.lineWidth = 1;
        // Probes from the edge of the orbit out to the closest records.
        for (const { point, distance } of nearest(points, focus, reach * 0.85, LINKS, ring + 26)) {
          const ux = (point.x - focus.x) / distance;
          const uy = (point.y - focus.y) / distance;
          ctx.strokeStyle = `rgba(${TEAL}, ${(1 - distance / (reach * 0.85)) * 0.75})`;
          ctx.beginPath();
          ctx.moveTo(focus.x + ux * ring, focus.y + uy * ring);
          ctx.lineTo(point.x, point.y);
          ctx.stroke();
        }
        // The orbit and its satellite, centred on the focus.
        ctx.strokeStyle = `rgba(${VIOLET}, 0.75)`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(focus.x, focus.y, ring, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "rgba(242, 243, 248, 0.95)";
        ctx.beginPath();
        ctx.arc(focus.x + Math.cos(SATELLITE_ANGLE) * ring, focus.y + Math.sin(SATELLITE_ANGLE) * ring, ring > 50 ? 4.5 : 3.5, 0, Math.PI * 2);
        ctx.fill();
      }
      return moving;
    };

    const loop = () => {
      frame = 0;
      if (draw()) frame = requestAnimationFrame(loop);
    };
    const kick = () => {
      if (!frame) frame = requestAnimationFrame(loop);
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      points = buildPoints(width, height);
      anchor = restingFocus(width, height);
      ({ ring, reach } = orbitSize(width));
      draw();
    };

    const onMove = (event) => {
      if (event.pointerType === "touch") return;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      pointer = x >= 0 && y >= 0 && x <= rect.width && y <= rect.height ? { x, y } : null;
      kick();
    };
    const onLeave = () => {
      pointer = null;
      kick();
    };

    resize();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
    if (observer) observer.observe(canvas);
    else window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("scroll", onLeave, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);

    return () => {
      if (observer) observer.disconnect();
      else window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("scroll", onLeave);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return <canvas ref={canvasRef} className="field" aria-hidden="true" />;
}
