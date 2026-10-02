"use client";

/**
 * Timeline control.
 *
 * 25 discrete positions, each an exact clock time. Moving the slider selects a
 * pre-computed frame - the geometry is never interpolated between hourly
 * frames, because interpolating a shadow polygon would produce a shape that
 * corresponds to no actual solar position.
 */

import { useEffect, useRef } from "react";
import type { SimulationFrame } from "@/lib/types";
import { formatDate } from "@/lib/format";

export interface TimelineProps {
  frames: SimulationFrame[];
  index: number;
  onIndexChange: (index: number) => void;
  playing: boolean;
  onPlayingChange: (playing: boolean) => void;
  /** Milliseconds between frames during playback. */
  frameIntervalMs: number;
  onIntervalChange: (ms: number) => void;
  disabled: boolean;
}
const SPEED_OPTIONS = [
  { label: "0.5×", value: 2000 },
  { label: "1×", value: 1000 },
  { label: "2×", value: 500 },
  { label: "4×", value: 250 },
];

export default function Timeline({
  frames,
  index,
  onIndexChange,
  playing,
  onPlayingChange,
  frameIntervalMs,
  onIntervalChange,
  disabled,
}: TimelineProps) {
  const frame = frames[index];
  const sliderRef = useRef<HTMLInputElement | null>(null);

  // Playback advances frame by frame and stops at the last frame rather than
  // looping silently, so a user who walks away sees a stable end state.
  // The current index is mirrored into a ref inside an effect (never during
  // render) so the timer is created once per play/speed change rather than
  // restarting on every tick.
  const latestIndex = useRef(index);
  useEffect(() => {
    latestIndex.current = index;
  }, [index]);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      const current = latestIndex.current;
      if (current >= frames.length - 1) {
        onPlayingChange(false);
        return;
      }
      onIndexChange(current + 1);
    }, frameIntervalMs);
    return () => window.clearInterval(timer);
  }, [playing, frameIntervalMs, frames.length, onIndexChange, onPlayingChange]);

  if (!frame) return null;

  const atStart = index === 0;
  const atEnd = index === frames.length - 1;

  return (
    <div className="border-t border-panel-border bg-panel px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <div className="flex items-baseline gap-3">
          <span className="tnum text-2xl font-semibold leading-none">
            {frame.local_time}
          </span>
          <span className="tnum text-sm text-muted">IST</span>
          <span className="text-sm text-muted">
            {formatDate(frame.date_local)}
          </span>
        </div>
        <div className="tnum text-xs text-muted">
          frame {index + 1} / {frames.length} · {frame.timestamp}
        </div>
      </div>

      <input
        ref={sliderRef}
        type="range"
        min={0}
        max={frames.length - 1}
        step={1}
        value={index}
        disabled={disabled}
        onChange={(event) => onIndexChange(Number(event.target.value))}
        aria-label="Simulation timeline, 1-hour increments"
        aria-valuetext={`${frame.local_time} on ${frame.date_local}`}
        className="mt-3 w-full cursor-pointer accent-[var(--accent)] disabled:cursor-not-allowed"
        list="timeline-ticks"
      />

      {/* Tick labels: exact clock times, laid out under the slider. */}
      <div
        id="timeline-ticks"
        className="tnum mt-1 flex justify-between text-[10px] text-muted"
        aria-hidden="true"
      >
        {frames.map((tick, i) => (
          <span
            key={tick.slug}
            className={
              i === index ? "font-semibold text-[var(--accent)]" : undefined
            }
          >
            {tick.local_time.slice(0, 2)}
          </span>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onIndexChange(Math.max(0, index - 1))}
          disabled={disabled || atStart}
          className="tnum border border-panel-border px-3 py-1.5 text-sm hover:bg-[var(--background)] disabled:opacity-40"
        >
          ◀ Previous
        </button>

        <button
          type="button"
          onClick={() => onPlayingChange(!playing)}
          disabled={disabled}
          className="tnum border border-panel-border bg-[var(--background)] px-4 py-1.5 text-sm hover:bg-[var(--panel-border)]/40 disabled:opacity-40"
          aria-pressed={playing}
        >
          {playing ? "❙❙ Pause" : "▶ Play"}
        </button>

        <button
          type="button"
          onClick={() => onIndexChange(Math.min(frames.length - 1, index + 1))}
          disabled={disabled || atEnd}
          className="tnum border border-panel-border px-3 py-1.5 text-sm hover:bg-[var(--background)] disabled:opacity-40"
        >
          Next ▶
        </button>

        <label className="ml-2 flex items-center gap-2 text-xs text-muted">
          Speed
          <select
            value={frameIntervalMs}
            onChange={(event) => onIntervalChange(Number(event.target.value))}
            disabled={disabled}
            className="tnum border border-panel-border bg-panel px-2 py-1 text-xs"
          >
            {SPEED_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <span
          className={`tnum ml-auto text-xs ${
            frame.shadow_emitted ? "text-muted" : "font-semibold text-[var(--night)]"
          }`}
        >
          {frame.shadow_emitted
            ? "Solar shadow active"
            : frame.sun_above_horizon
              ? "Below emission threshold"
              : "Sun below horizon"}
        </span>
      </div>
    </div>
  );
}
