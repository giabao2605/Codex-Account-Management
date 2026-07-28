export const DEFAULT_NORMAL_MAP_CACHE_LIMIT = 64;

const GEOMETRY_STEP = 4;
const RADIUS_STEP = 2;
const CONTROL_TEXTURE_SIZE = Object.freeze({
  width: 128,
  height: 64,
});
const PANEL_TEXTURE_SIZE = Object.freeze({
  width: 256,
  height: 192,
});

export type NormalMapKind = "control" | "panel";

export interface NormalMapRequest {
  readonly kind: NormalMapKind;
  readonly width: number;
  readonly height: number;
  readonly radius: number;
}

export interface QuantizedNormalMapGeometry extends NormalMapRequest {
  readonly textureWidth: number;
  readonly textureHeight: number;
}

export interface NormalMapSample {
  readonly r: number;
  readonly g: number;
  readonly b: 0.5;
  readonly a: 1;
}

export interface NormalMap {
  readonly key: string;
  readonly kind: NormalMapKind;
  readonly width: number;
  readonly height: number;
  readonly radius: number;
  readonly textureWidth: number;
  readonly textureHeight: number;
  sample(x: number, y: number): NormalMapSample;
  toRgbaBytes(): Uint8ClampedArray;
}

function requireFinite(name: string, value: number): void {
  if (!Number.isFinite(value)) {
    throw new RangeError(`${name} must be finite`);
  }
}

function quantizePositive(name: string, value: number, step: number): number {
  requireFinite(name, value);
  if (value <= 0) {
    throw new RangeError(`${name} must be greater than zero`);
  }
  return Math.max(step, Math.round(value / step) * step);
}

function quantizeRadius(value: number, maximum: number): number {
  requireFinite("radius", value);
  if (value < 0) {
    throw new RangeError("radius must not be negative");
  }
  return Math.min(maximum, Math.round(value / RADIUS_STEP) * RADIUS_STEP);
}

export function quantizeNormalMapGeometry(
  request: NormalMapRequest,
): QuantizedNormalMapGeometry {
  const width = quantizePositive("width", request.width, GEOMETRY_STEP);
  const height = quantizePositive("height", request.height, GEOMETRY_STEP);
  const radius = quantizeRadius(request.radius, Math.min(width, height) / 2);
  const texture =
    request.kind === "panel" ? PANEL_TEXTURE_SIZE : CONTROL_TEXTURE_SIZE;

  return Object.freeze({
    kind: request.kind,
    width,
    height,
    radius,
    textureWidth: texture.width,
    textureHeight: texture.height,
  });
}

function keyFromGeometry(geometry: QuantizedNormalMapGeometry): string {
  return [
    geometry.kind,
    `${geometry.width}x${geometry.height}`,
    `r${geometry.radius}`,
    `t${geometry.textureWidth}x${geometry.textureHeight}`,
  ].join(":");
}

export function makeNormalMapKey(request: NormalMapRequest): string {
  return keyFromGeometry(quantizeNormalMapGeometry(request));
}

interface SignedDistanceResult {
  readonly distance: number;
  readonly normalX: number;
  readonly normalY: number;
}

function signOrZero(value: number): number {
  if (value > 0) {
    return 1;
  }
  if (value < 0) {
    return -1;
  }
  return 0;
}

function roundedRectangleDistance(
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): SignedDistanceResult {
  const innerHalfWidth = width / 2 - radius;
  const innerHalfHeight = height / 2 - radius;
  const qx = Math.abs(x) - innerHalfWidth;
  const qy = Math.abs(y) - innerHalfHeight;
  const outsideX = Math.max(qx, 0);
  const outsideY = Math.max(qy, 0);
  const outsideLength = Math.hypot(outsideX, outsideY);
  const distance = outsideLength + Math.min(Math.max(qx, qy), 0) - radius;

  if (outsideLength > 0) {
    return {
      distance,
      normalX: signOrZero(x) * (outsideX / outsideLength),
      normalY: signOrZero(y) * (outsideY / outsideLength),
    };
  }
  if (qx > qy) {
    return {
      distance,
      normalX: signOrZero(x),
      normalY: 0,
    };
  }
  return {
    distance,
    normalX: 0,
    normalY: signOrZero(y),
  };
}

function smoothEdgeInfluence(insideDistance: number, edgeBand: number): number {
  const linear = Math.max(0, Math.min(1, 1 - insideDistance / edgeBand));
  return linear * linear * (3 - 2 * linear);
}

class GeneratedNormalMap implements NormalMap {
  readonly key: string;
  readonly kind: NormalMapKind;
  readonly width: number;
  readonly height: number;
  readonly radius: number;
  readonly textureWidth: number;
  readonly textureHeight: number;
  readonly #redGreenChannels: Float32Array;

  constructor(
    geometry: QuantizedNormalMapGeometry,
    redGreenChannels: Float32Array,
  ) {
    this.key = keyFromGeometry(geometry);
    this.kind = geometry.kind;
    this.width = geometry.width;
    this.height = geometry.height;
    this.radius = geometry.radius;
    this.textureWidth = geometry.textureWidth;
    this.textureHeight = geometry.textureHeight;
    this.#redGreenChannels = redGreenChannels;
    Object.freeze(this);
  }

  sample(x: number, y: number): NormalMapSample {
    if (
      !Number.isInteger(x)
      || !Number.isInteger(y)
      || x < 0
      || y < 0
      || x >= this.textureWidth
      || y >= this.textureHeight
    ) {
      throw new RangeError("sample coordinates must be integer texture coordinates");
    }
    const offset = (y * this.textureWidth + x) * 2;
    return Object.freeze({
      r: this.#redGreenChannels[offset] ?? 0.5,
      g: this.#redGreenChannels[offset + 1] ?? 0.5,
      b: 0.5,
      a: 1,
    });
  }

  toRgbaBytes(): Uint8ClampedArray {
    const pixels = new Uint8ClampedArray(
      this.textureWidth * this.textureHeight * 4,
    );
    for (let index = 0; index < this.textureWidth * this.textureHeight; index += 1) {
      const sourceOffset = index * 2;
      const targetOffset = index * 4;
      pixels[targetOffset] = Math.round(
        (this.#redGreenChannels[sourceOffset] ?? 0.5) * 255,
      );
      pixels[targetOffset + 1] = Math.round(
        (this.#redGreenChannels[sourceOffset + 1] ?? 0.5) * 255,
      );
      pixels[targetOffset + 2] = 128;
      pixels[targetOffset + 3] = 255;
    }
    return pixels;
  }
}

export function generateNormalMap(request: NormalMapRequest): NormalMap {
  const geometry = quantizeNormalMapGeometry(request);
  const channels = new Float32Array(
    geometry.textureWidth * geometry.textureHeight * 2,
  );
  channels.fill(0.5);
  const edgeBand = Math.max(
    4,
    Math.min(24, Math.min(geometry.width, geometry.height) * 0.28),
  );

  for (let y = 0; y < geometry.textureHeight; y += 1) {
    const geometryY =
      ((y + 0.5) / geometry.textureHeight - 0.5) * geometry.height;
    for (let x = 0; x < geometry.textureWidth; x += 1) {
      const geometryX =
        ((x + 0.5) / geometry.textureWidth - 0.5) * geometry.width;
      const { distance, normalX, normalY } = roundedRectangleDistance(
        geometryX,
        geometryY,
        geometry.width,
        geometry.height,
        geometry.radius,
      );
      if (distance > 0) {
        continue;
      }
      const influence = smoothEdgeInfluence(-distance, edgeBand);
      if (influence === 0) {
        continue;
      }
      const offset = (y * geometry.textureWidth + x) * 2;
      channels[offset] = 0.5 + normalX * influence * 0.5;
      channels[offset + 1] = 0.5 + normalY * influence * 0.5;
    }
  }

  return new GeneratedNormalMap(geometry, channels);
}

export class NormalMapCache {
  readonly maxEntries: number;
  readonly #entries = new Map<string, NormalMap>();

  constructor(maxEntries = DEFAULT_NORMAL_MAP_CACHE_LIMIT) {
    if (!Number.isInteger(maxEntries) || maxEntries <= 0) {
      throw new RangeError("maxEntries must be a positive integer");
    }
    this.maxEntries = maxEntries;
  }

  get size(): number {
    return this.#entries.size;
  }

  has(key: string): boolean {
    return this.#entries.has(key);
  }

  get(request: NormalMapRequest): NormalMap {
    const key = makeNormalMapKey(request);
    const cached = this.#entries.get(key);
    if (cached) {
      this.#entries.delete(key);
      this.#entries.set(key, cached);
      return cached;
    }

    const generated = generateNormalMap(request);
    this.#entries.set(key, generated);
    if (this.#entries.size > this.maxEntries) {
      const leastRecentlyUsed = this.#entries.keys().next().value;
      if (leastRecentlyUsed !== undefined) {
        this.#entries.delete(leastRecentlyUsed);
      }
    }
    return generated;
  }

  clear(): void {
    this.#entries.clear();
  }
}
