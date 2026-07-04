import { useEffect, useRef } from "react";

// Canvas node-graph "book sync" animation (ported from the author's
// rag_book_sync_nodes_only.html prototype): eight chunk nodes orbit a
// pulsing hub, lighting up one by one with pulses travelling the edges,
// then the cycle resets. Colors follow the viewer's light/dark mode via
// the `dark` prop rather than prefers-color-scheme.

const W = 420;
const H = 380;
const CX = W / 2;
const CY = H / 2;
const ORBIT_R = 122;
const NODE_COUNT = 8;
const HUB_R = 28;

type Rgb = { r: number; g: number; b: number };

const PALETTE: Record<string, (dark: boolean) => Rgb> = {
  large:      (d) => d ? { r: 129, g: 140, b: 248 } : { r:  99, g: 102, b: 241 },
  medium:     (d) => d ? { r: 167, g: 139, b: 250 } : { r: 139, g:  92, b: 246 },
  small:      (d) => d ? { r: 192, g: 132, b: 252 } : { r: 168, g:  85, b: 247 },
  edge:       (d) => d ? { r:  55, g:  48, b: 163 } : { r: 224, g: 231, b: 255 },
  edgeActive: (d) => d ? { r: 129, g: 140, b: 248 } : { r:  99, g: 102, b: 241 },
  hub1:       (d) => d ? { r: 129, g: 140, b: 248 } : { r:  79, g:  70, b: 229 },
  hub2:       (d) => d ? { r:  55, g:  48, b: 163 } : { r:  99, g: 102, b: 241 },
  pulse:      (d) => d ? { r: 192, g: 132, b: 252 } : { r: 168, g:  85, b: 247 },
  particle:   (d) => d ? { r: 167, g: 139, b: 250 } : { r:  99, g: 102, b: 241 },
};

const NODE_COLORS = ["large", "medium", "small", "medium", "small", "medium", "small", "large"];

function rgb(c: Rgb, a = 1): string {
  return `rgba(${c.r},${c.g},${c.b},${a})`;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

interface Props {
  dark: boolean;
  // rendered size; the canvas draws at 420x380 and scales down crisply
  width?: number;
}

export default function SyncAnimation({ dark, width = 260 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const darkRef = useRef(dark);
  darkRef.current = dark;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const P = (key: string) => PALETTE[key](darkRef.current);

    const nodes = Array.from({ length: NODE_COUNT }, (_, i) => {
      const angle = (i / NODE_COUNT) * Math.PI * 2 - Math.PI / 2;
      return {
        baseAngle: angle,
        baseR: ORBIT_R,
        r: i === 0 || i === 7 ? 16 : i % 3 === 0 ? 14 : 12,
        colorKey: NODE_COLORS[i],
        lit: false,
        litTime: 0,
        freqA: 0.47 + Math.random() * 0.4,
        freqB: 0.31 + Math.random() * 0.3,
        freqC: 0.61 + Math.random() * 0.5,
        phaseA: Math.random() * Math.PI * 2,
        phaseB: Math.random() * Math.PI * 2,
        phaseC: Math.random() * Math.PI * 2,
        radialDrift: 18 + Math.random() * 14,
        angularDrift: 0.18 + Math.random() * 0.14,
        orbitDir: i % 2 === 0 ? 1 : -1,
        orbitSpeed: 0.004 + Math.random() * 0.003,
      };
    });

    function nodePos(n: (typeof nodes)[number], t: number) {
      const orbitAngle = n.baseAngle + n.orbitDir * n.orbitSpeed * t;
      const r = n.baseR + n.radialDrift * Math.sin(n.freqA * t + n.phaseA);
      const a = orbitAngle + n.angularDrift * Math.sin(n.freqB * t + n.phaseB);
      const wx = 5 * Math.sin(n.freqC * t + n.phaseC);
      const wy = 5 * Math.cos(n.freqC * t + n.phaseC + 1.1);
      return { x: CX + Math.cos(a) * r + wx, y: CY + Math.sin(a) * r + wy };
    }

    const edges: [number, number][] = [];
    for (let i = 0; i < NODE_COUNT; i++) edges.push([i, (i + 1) % NODE_COUNT]);
    edges.push([0, 4], [1, 5], [2, 6], [3, 7]);

    let pulses: { from: number; to: number; prog: number; speed: number }[] = [];
    const spawnPulse = (from: number, to: number) => {
      pulses.push({ from, to, prog: 0, speed: 0.016 + Math.random() * 0.014 });
    };

    let t = 0, frame = 0, nextLight = 0, lastLitFrame = 0, done = false, activeEdge = 0;
    let rafId = 0;
    let resetTimer: ReturnType<typeof setTimeout> | null = null;

    function tick() {
      if (!ctx) return;
      t += 0.016;
      frame++;
      ctx.clearRect(0, 0, W, H);
      const isDark = darkRef.current;
      const pos = nodes.map((n) => nodePos(n, t));

      // ambient particles
      const particleCol = P("particle");
      for (let i = 0; i < 24; i++) {
        const a = (i / 24) * Math.PI * 2 + t * 0.28;
        const r = ORBIT_R + 50 + Math.sin(t * 0.65 + i * 0.85) * 18;
        ctx.beginPath();
        ctx.arc(CX + Math.cos(a) * r, CY + Math.sin(a) * r, 1.5, 0, Math.PI * 2);
        ctx.fillStyle = rgb(particleCol, 0.08 + 0.04 * Math.sin(t * 1.1 + i));
        ctx.fill();
      }

      // edges
      edges.forEach(([a, b], ei) => {
        const pa = pos[a], pb = pos[b];
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        if (ei <= activeEdge) {
          ctx.strokeStyle = rgb(P("edgeActive"), 0.28);
          ctx.lineWidth = 1;
          ctx.setLineDash([]);
        } else {
          ctx.strokeStyle = rgb(P("edge"), isDark ? 0.22 : 0.55);
          ctx.lineWidth = 0.5;
          ctx.setLineDash([3, 5]);
        }
        ctx.stroke();
        ctx.setLineDash([]);
      });

      // spokes from lit nodes to the hub
      nodes.forEach((n, i) => {
        if (!n.lit) return;
        ctx.beginPath();
        ctx.moveTo(CX, CY);
        ctx.lineTo(pos[i].x, pos[i].y);
        ctx.strokeStyle = rgb(P("edgeActive"), 0.18);
        ctx.lineWidth = 0.8;
        ctx.stroke();
      });

      // hub
      const pulse = 0.5 + 0.5 * Math.sin(t * 2.0);
      const h1 = P("hub1"), h2 = P("hub2");
      ctx.beginPath();
      ctx.arc(CX, CY, HUB_R + 10 + pulse * 7, 0, Math.PI * 2);
      ctx.fillStyle = rgb(h1, (isDark ? 0.18 : 0.1) * (0.6 + 0.4 * pulse));
      ctx.fill();
      ctx.beginPath();
      ctx.arc(CX, CY, HUB_R, 0, Math.PI * 2);
      const g = ctx.createRadialGradient(CX, CY - 6, 2, CX, CY, HUB_R);
      g.addColorStop(0, rgb(h1, 0.92));
      g.addColorStop(1, rgb(h2, 0.96));
      ctx.fillStyle = g;
      ctx.fill();
      ctx.strokeStyle = rgb(P("medium"), 0.55);
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(CX, CY, HUB_R + 7, t * 0.8, t * 0.8 + Math.PI * 1.3);
      ctx.strokeStyle = rgb(P("small"), 0.4);
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(CX, CY, HUB_R + 7, t * 0.8 + Math.PI, t * 0.8 + Math.PI * 1.7);
      ctx.strokeStyle = rgb(P("medium"), 0.25);
      ctx.lineWidth = 1;
      ctx.stroke();

      // pulses in flight
      const pulseCol = P("pulse");
      pulses.forEach((p) => {
        const pa = pos[p.from], pb = pos[p.to];
        const px = lerp(pa.x, pb.x, p.prog);
        const py = lerp(pa.y, pb.y, p.prog);
        ctx.beginPath();
        ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fillStyle = rgb(pulseCol, 0.85);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(px, py, 8, 0, Math.PI * 2);
        ctx.fillStyle = rgb(pulseCol, 0.18);
        ctx.fill();
      });

      // nodes
      nodes.forEach((n, i) => {
        const { x, y } = pos[i];
        const col = P(n.colorKey);
        const bright = { r: Math.min(255, col.r + 50), g: Math.min(255, col.g + 50), b: Math.min(255, col.b + 50) };
        const lit = n.lit ? 1 : 0;
        const age = n.lit ? Math.min((t - n.litTime) * 1.8, 1) : 0;
        if (n.lit) {
          ctx.beginPath();
          ctx.arc(x, y, n.r + 11, 0, Math.PI * 2);
          ctx.fillStyle = rgb(col, 0.12 * age);
          ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(x, y, n.r + 3, 0, Math.PI * 2);
        ctx.fillStyle = rgb(col, (isDark ? 0.15 : 0.12) + 0.1 * lit);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(x, y, n.r, 0, Math.PI * 2);
        const ng = ctx.createRadialGradient(x, y - 3, 1, x, y, n.r);
        ng.addColorStop(0, rgb(bright, 0.5 + 0.35 * lit));
        ng.addColorStop(1, rgb(col, 0.7 + 0.25 * lit));
        ctx.fillStyle = ng;
        ctx.fill();
        ctx.strokeStyle = rgb(bright, 0.35 + 0.4 * lit);
        ctx.lineWidth = 1;
        ctx.stroke();
      });

      // progression: light nodes one by one, then reset after a beat
      pulses.forEach((p) => { p.prog += p.speed; });
      pulses = pulses.filter((p) => p.prog < 1.05);
      if (!done && frame - lastLitFrame > 38) {
        lastLitFrame = frame;
        if (nextLight < NODE_COUNT) {
          nodes[nextLight].lit = true;
          nodes[nextLight].litTime = t;
          spawnPulse(nextLight, (nextLight + 2) % NODE_COUNT);
          if (nextLight > 0) spawnPulse(nextLight - 1, nextLight);
          activeEdge = nextLight;
          nextLight++;
          if (nextLight === NODE_COUNT) {
            done = true;
            resetTimer = setTimeout(() => {
              done = false; nextLight = 0; frame = 0; lastLitFrame = 0;
              nodes.forEach((n) => { n.lit = false; n.litTime = 0; });
              pulses = []; activeEdge = 0;
            }, 2400);
          }
        }
      }
      if (frame % 20 === 0 && !done) {
        const a = Math.floor(Math.random() * NODE_COUNT);
        spawnPulse(a, (a + 1 + Math.floor(Math.random() * (NODE_COUNT - 2))) % NODE_COUNT);
      }
      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafId);
      if (resetTimer) clearTimeout(resetTimer);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      width={W}
      height={H}
      style={{ width, height: (width * H) / W }}
      aria-label="Book syncing animation"
    />
  );
}
