/**
 * A tiny two-note WebAudio chime — no audio asset to download, works offline.
 * Used sparingly: a new booking or arrival landing in the queue. Guarded so it
 * only fires after the receptionist's first tap (autoplay policy) and never
 * throws on browsers without WebAudio.
 */
let ctx: AudioContext | null = null;
let armed = false;

export function armSound() {
  armed = true;
  if (!ctx && typeof window !== "undefined") {
    const AC = window.AudioContext ?? (window as any).webkitAudioContext;
    if (AC) ctx = new AC();
  }
  if (ctx?.state === "suspended") ctx.resume().catch(() => {});
}

export function chime() {
  if (!armed || !ctx) return;
  try {
    const now = ctx.currentTime;
    [0, 0.14].forEach((offset, i) => {
      const osc = ctx!.createOscillator();
      const gain = ctx!.createGain();
      osc.type = "sine";
      osc.frequency.value = i === 0 ? 660 : 880;
      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.12, now + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.18);
      osc.connect(gain).connect(ctx!.destination);
      osc.start(now + offset);
      osc.stop(now + offset + 0.2);
    });
  } catch {
    /* ignore */
  }
}
