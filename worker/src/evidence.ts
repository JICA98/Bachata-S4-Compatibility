import {PRIVATE_PATTERN} from "./privacy";

export const MAX_IMAGE_BYTES = 1.5 * 1024 * 1024;
export const MAX_PIXELS = 4_000_000;
export const MAX_GZIP_BYTES = 1.5 * 1024 * 1024;
export const MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024;

export interface ImagesBinding {
  info(bytes: ArrayBuffer | Uint8Array): Promise<{width: number; height: number; format?: string}>;
  input(bytes: ArrayBuffer | Uint8Array): {
    transform(options: {width: number; height: number; fit: string}): {
      output(options: {format: string; quality: number; anim: boolean}): Promise<{
        response(): Response;
      }>;
    };
  };
}

async function pipeBytes(bytes: Uint8Array, transform: CompressionStream | DecompressionStream): Promise<Uint8Array> {
  const stream = new Blob([bytes]).stream().pipeThrough(transform);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map(v => v.toString(16).padStart(2, "0")).join("");
}

export async function sanitizeLogGzip(bytes: Uint8Array): Promise<Uint8Array> {
  if (bytes.byteLength > MAX_GZIP_BYTES) throw new Error("Log exceeds size limit");
  const uncompressed = await pipeBytes(bytes, new DecompressionStream("gzip"));
  if (uncompressed.byteLength > MAX_UNCOMPRESSED_BYTES) throw new Error("Log exceeds size limit");
  const text = new TextDecoder().decode(uncompressed);
  if (PRIVATE_PATTERN.test(text)) throw new Error("Submission contains a private identifier or local path");
  return pipeBytes(uncompressed, new CompressionStream("gzip"));
}

export async function reencodeScreenshot(images: ImagesBinding, bytes: Uint8Array): Promise<Uint8Array> {
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_IMAGE_BYTES) throw new Error("Screenshot exceeds size limit");
  let info: {width: number; height: number};
  try {
    info = await images.info(bytes);
  } catch {
    throw new Error("Invalid screenshot");
  }
  if (!info.width || !info.height || info.width * info.height > MAX_PIXELS) {
    throw new Error("Screenshot exceeds pixel limit");
  }
  const out = await images.input(bytes)
    .transform({width: 1920, height: 1920, fit: "scale-down"})
    .output({format: "image/webp", quality: 80, anim: false});
  return new Uint8Array(await out.response().arrayBuffer());
}
