import {describe, expect, it} from "vitest";
import {parsePerformanceFromLog} from "./performance";

const line = (elapsed: number, source: number, output: number, ft: number, fg: "on" | "off") =>
  `[2026-09-15T05:00:00Z] [App.Performance] <Info> elapsedMs=${elapsed} sourceFps=${source.toFixed(2)} outputFps=${output.toFixed(2)} frameTimeMs=${ft.toFixed(2)} fg=${fg}`;

describe("parsePerformanceFromLog", () => {
  it("ignores boot window and zero fps, then averages native fps", () => {
    const text = [
      line(0, 5, 5, 200, "off"),
      line(2000, 0, 0, 0, "off"),
      line(12000, 30, 30, 33.3, "off"),
      line(14000, 32, 32, 31.2, "off"),
      line(16000, 28, 28, 35.7, "off"),
      line(18000, 30, 30, 33.3, "off"),
      line(20000, 31, 31, 32.2, "off"),
      line(22000, 30, 30, 33.3, "off"),
    ].join("\n");
    const stats = parsePerformanceFromLog(text);
    expect(stats?.nativeAverageFps).toBeCloseTo(30.17, 1);
    expect(stats?.testDurationSeconds).toBe(22);
    expect(stats?.outputAverageFps).toBeUndefined();
    expect(stats?.nativeOnePercentLowFps).toBeUndefined();
  });

  it("accepts legacy fps= lines", () => {
    const text = Array.from({length: 6}, (_, i) =>
      `[t] [App.Performance] <Info> elapsedMs=${12000 + i * 2000} fps=20.00 frameTimeMs=50.00`,
    ).join("\n");
    expect(parsePerformanceFromLog(text)?.nativeAverageFps).toBe(20);
  });

  it("omits stats when fewer than 5 post-boot samples", () => {
    const text = line(12000, 30, 30, 33, "off");
    expect(parsePerformanceFromLog(text)).toBeUndefined();
  });

  it("sets outputAverageFps only when fg=on and output differs", () => {
    const text = Array.from({length: 6}, (_, i) => line(12000 + i * 2000, 30, 58, 33.3, "on")).join("\n");
    const stats = parsePerformanceFromLog(text);
    expect(stats?.nativeAverageFps).toBe(30);
    expect(stats?.outputAverageFps).toBe(58);
  });
});
