import "./voice.css";

// What each call phase is called on screen. The same words are the avatar's accessible name, so the state is never
// conveyed by motion alone.
export const PHASE_LABELS = {
  idle: "Ready to start a call",
  connecting: "Connecting",
  listening: "Listening",
  recording: "Listening to you",
  thinking: "Thinking",
  speaking: "Speaking",
  waiting: "On hold while a specialist reviews",
  resolved: "Resolved",
  ended: "Call ended",
};

const BARS = [0, 1, 2, 3, 4];

// A calm illustrated agent wearing a headset. Pure SVG with CSS animation (see voice.css): slow ripples while
// listening, drifting dots while thinking, soft level bars while speaking, a breathing glow while on hold, and a
// quiet check mark once resolved. Everything stops under prefers-reduced-motion.
export default function HeadsetAvatar({ phase = "idle", level = 0, name = "Cosmo", size = 132 }) {
  const label = PHASE_LABELS[phase] || PHASE_LABELS.idle;
  return (
    <svg
      className="headset"
      data-state={phase}
      style={{ "--level": Number(level.toFixed(2)), width: size, height: size }}
      viewBox="0 0 160 160"
      role="img"
      aria-label={`${name}, the voice assistant. ${label}.`}
    >
      <circle className="hs-bg" cx="80" cy="80" r="74" />
      <g className="hs-rings" aria-hidden="true">
        <circle className="hs-ring hs-ring-1" cx="80" cy="70" r="44" />
        <circle className="hs-ring hs-ring-2" cx="80" cy="70" r="44" />
        <circle className="hs-ring hs-ring-3" cx="80" cy="70" r="44" />
      </g>

      <g className="hs-figure" aria-hidden="true">
        <path className="hs-torso" d="M26 152 C26 120 52 106 80 106 C108 106 134 120 134 152 Z" />
        <rect className="hs-skin" x="71" y="92" width="18" height="18" rx="7" />
        <ellipse className="hs-skin" cx="80" cy="68" rx="25" ry="28" />
        <path className="hs-hair" d="M54 68 C52 42 67 33 82 33 C99 33 109 46 106 68 C100 57 92 52 80 52 C68 52 60 57 54 68 Z" />
        <path className="hs-face" d="M68 71 q4 3 8 0 M84 71 q4 3 8 0 M72 83 q8 6 16 0" />
        <path className="hs-band" d="M51 70 C48 40 65 27 80 27 C96 27 113 40 109 70" />
        <rect className="hs-cup" x="44" y="62" width="11" height="22" rx="5.5" />
        <rect className="hs-cup" x="105" y="62" width="11" height="22" rx="5.5" />
        <path className="hs-boom" d="M49 82 C49 99 60 101 71 95" />
        <circle className="hs-mic" cx="73" cy="94" r="4" />
      </g>

      <g className="hs-dots" aria-hidden="true">
        <circle cx="116" cy="34" r="3.5" />
        <circle cx="127" cy="34" r="3.5" />
        <circle cx="138" cy="34" r="3.5" />
      </g>
      <g className="hs-bars" aria-hidden="true">
        {BARS.map((index) => (
          <rect key={index} className={`hs-bar hs-bar-${index}`} x={52 + index * 12} y="132" width="6" height="18" rx="3" />
        ))}
      </g>
      <g className="hs-check" aria-hidden="true">
        <circle cx="126" cy="124" r="17" />
        <path d="M118 124 l6 6 l12 -13" />
      </g>
    </svg>
  );
}
