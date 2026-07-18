// Attention alert for long-running work (e.g. a slow RAG answer) that completes
// while the user has tabbed away. Plays a short chime and flashes a 🔔 into the
// document title until the tab regains focus / is clicked back to.

let flashInterval: ReturnType<typeof setInterval> | null = null;
let baseTitle = "";
let listening = false;

function playChime(): void {
  try {
    const AudioCtx =
      window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    // Resume in case the context starts suspended; the send click already
    // satisfied the autoplay gesture requirement in practice.
    void ctx.resume?.();

    // Two-note rising chime (A5 → C#6).
    [880, 1108.73].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const start = ctx.currentTime + i * 0.18;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.2, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.35);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.4);
    });

    setTimeout(() => void ctx.close(), 1200);
  } catch {
    // Audio unavailable — the title flash still alerts the user.
  }
}

function stopFlash(): void {
  if (flashInterval !== null) {
    clearInterval(flashInterval);
    flashInterval = null;
    document.title = baseTitle;
  }
  if (listening) {
    listening = false;
    window.removeEventListener("focus", onRefocus);
    document.removeEventListener("visibilitychange", onVisibility);
  }
}

function onRefocus(): void {
  stopFlash();
}

function onVisibility(): void {
  if (document.visibilityState === "visible") stopFlash();
}

function startFlash(): void {
  if (flashInterval !== null) {
    // Already flashing from a prior answer — reset the base title so we don't
    // bake a "🔔 …" prefix into the restore value.
    return;
  }
  baseTitle = document.title;
  let on = false;
  flashInterval = setInterval(() => {
    document.title = on ? baseTitle : `🔔 Answer ready · ${baseTitle}`;
    on = !on;
  }, 1000);

  if (!listening) {
    listening = true;
    window.addEventListener("focus", onRefocus);
    document.addEventListener("visibilitychange", onVisibility);
  }
}

/**
 * Alert the user that a slow answer just finished. No-op when the tab is
 * already focused — you only get the chime + title bell if you've tabbed away.
 */
export function notifyAnswerReady(): void {
  if (document.hasFocus()) return;
  playChime();
  startFlash();
}
