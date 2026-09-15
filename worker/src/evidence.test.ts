import {describe, expect, it} from "vitest";
import {reencodeScreenshot, sanitizeLogGzip, sha256Hex} from "./evidence";

const WEBP = new Uint8Array([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50]);

async function gzip(text: string): Promise<Uint8Array> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function gunzip(bytes: Uint8Array): Promise<string> {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}

const images = {
  async info(bytes: ArrayBuffer | Uint8Array) {
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (u8[0] === 0x3c) throw new Error("unsupported");
    return {width: 1920, height: 1080, format: "image/jpeg"};
  },
  input() {
    return {
      transform() {
        return {
          async output() {
            return {response: () => new Response(WEBP, {headers: {"content-type": "image/webp"}})};
          },
        };
      },
    };
  },
};

describe("sanitizeLogGzip", () => {
  it("re-gzips a clean log", async () => {
    const input = await gzip("elapsedMs=12000 fps=30.00 frameTimeMs=33.33\n");
    const out = await sanitizeLogGzip(input);
    expect(await gunzip(out)).toBe("elapsedMs=12000 fps=30.00 frameTimeMs=33.33\n");
  });

  it("rejects a log that still contains a private path", async () => {
    const input = await gzip("hello /data/user/0/secret\n");
    await expect(sanitizeLogGzip(input)).rejects.toThrow(/private identifier/i);
  });
});

describe("reencodeScreenshot", () => {
  it("returns Worker Images WebP output", async () => {
    const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);
    const out = await reencodeScreenshot(images, jpeg);
    expect(out[0]).toBe(0x52);
    expect(String.fromCharCode(...out.slice(8, 12))).toBe("WEBP");
  });

  it("rejects SVG", async () => {
    await expect(reencodeScreenshot(images, new Uint8Array([0x3c, 0x73, 0x76, 0x67]))).rejects.toThrow(/Invalid screenshot|unsupported/i);
  });

  it("rejects oversized uploads", async () => {
    const tooBig = new Uint8Array(1.5 * 1024 * 1024 + 1);
    await expect(reencodeScreenshot(images, tooBig)).rejects.toThrow(/size/i);
  });

  it("rejects images over 4 megapixels", async () => {
    const huge = {
      ...images,
      async info() {
        return {width: 4001, height: 1001, format: "image/jpeg"};
      },
    };
    await expect(reencodeScreenshot(huge, new Uint8Array([0xff, 0xd8]))).rejects.toThrow(/pixel/i);
  });
});

describe("sha256Hex", () => {
  it("hashes bytes", async () => {
    const digest = await sha256Hex(new TextEncoder().encode("abc"));
    expect(digest).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});
