export type FramePacing = "smooth" | "minor-stutter" | "stuttery" | "severe-stutter";

export interface PerformanceStats {
  nativeAverageFps: number;
  nativeOnePercentLowFps?: number;
  outputAverageFps?: number;
  testDurationSeconds: number;
  framePacing: FramePacing;
}

const NEW_RE = /elapsedMs=(\d+)\s+sourceFps=([\d.]+)\s+outputFps=([\d.]+)\s+frameTimeMs=([\d.]+)\s+fg=(on|off)/;
const OLD_RE = /elapsedMs=(\d+)\s+fps=([\d.]+)\s+frameTimeMs=([\d.]+)/;

interface Sample {
  elapsedMs: number;
  sourceFps: number;
  outputFps: number;
  frameTimeMs: number;
  fgOn: boolean;
}

function parseLine(line: string): Sample | undefined {
  const newer = line.match(NEW_RE);
  if (newer) {
    return {
      elapsedMs: Number(newer[1]),
      sourceFps: Number(newer[2]),
      outputFps: Number(newer[3]),
      frameTimeMs: Number(newer[4]),
      fgOn: newer[5] === "on",
    };
  }
  const older = line.match(OLD_RE);
  if (older) {
    const fps = Number(older[2]);
    return {
      elapsedMs: Number(older[1]),
      sourceFps: fps,
      outputFps: fps,
      frameTimeMs: Number(older[3]),
      fgOn: false,
    };
  }
  return undefined;
}

function mean(values: number[]): number {
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function percentile(values: number[], p: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor((p / 100) * (sorted.length - 1))));
  return sorted[index];
}

function pacing(frameTimes: number[]): FramePacing {
  const avg = mean(frameTimes);
  if (avg <= 0) return "severe-stutter";
  const variance = mean(frameTimes.map(v => (v - avg) ** 2));
  const cv = Math.sqrt(variance) / avg;
  if (cv < 0.08) return "smooth";
  if (cv < 0.18) return "minor-stutter";
  if (cv < 0.35) return "stuttery";
  return "severe-stutter";
}

export function parsePerformanceFromLog(text: string): PerformanceStats | undefined {
  const samples = text.split(/\r?\n/).map(parseLine).filter((s): s is Sample => !!s)
    .filter(s => s.elapsedMs >= 10000 && s.sourceFps > 0);
  if (samples.length < 5) return undefined;
  const span = samples[samples.length - 1].elapsedMs - samples[0].elapsedMs;
  if (span < 10000) return undefined;
  const native = samples.map(s => s.sourceFps);
  const nativeAverageFps = Math.round(mean(native) * 100) / 100;
  const stats: PerformanceStats = {
    nativeAverageFps,
    testDurationSeconds: Math.max(1, Math.round(samples[samples.length - 1].elapsedMs / 1000)),
    framePacing: pacing(samples.map(s => s.frameTimeMs)),
  };
  if (samples.length >= 20) stats.nativeOnePercentLowFps = Math.round(percentile(native, 1) * 100) / 100;
  const fgOn = samples.some(s => s.fgOn);
  const outputMean = mean(samples.map(s => s.outputFps));
  if (fgOn && Math.abs(outputMean - nativeAverageFps) > 0.5) {
    stats.outputAverageFps = Math.round(outputMean * 100) / 100;
  }
  return stats;
}
