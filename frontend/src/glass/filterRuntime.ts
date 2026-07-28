import { readonly, shallowRef, type DeepReadonly, type Ref } from "vue";

import {
  GlassFilterRegistry,
  type GlassFilterLease,
} from "./filterRegistry.ts";
import type { NormalMap, NormalMapRequest } from "./normalMap.ts";

export interface RenderableGlassFilter {
  readonly key: string;
  readonly filterId: string;
  readonly dataUrl: string;
  readonly references: number;
  readonly displacement: number;
}

export interface RuntimeGlassFilterLease extends GlassFilterLease {
  readonly dataUrl: string;
}

interface RuntimeGlassFilterEntry extends RenderableGlassFilter {
  readonly generation: symbol;
}

const registry = new GlassFilterRegistry();
const EMPTY_DESCRIPTORS: readonly RenderableGlassFilter[] = Object.freeze([]);
const descriptors = shallowRef<readonly RenderableGlassFilter[]>(
  EMPTY_DESCRIPTORS,
);
const dataUrls = new Map<string, string>();
const runtimeEntries = new Map<string, RuntimeGlassFilterEntry>();

function normalMapDataUrl(map: NormalMap): string {
  const cached = dataUrls.get(map.key);
  if (cached) return cached;
  if (typeof document === "undefined") return "";
  const canvas = document.createElement("canvas");
  canvas.width = map.textureWidth;
  canvas.height = map.textureHeight;
  const context = canvas.getContext("2d");
  if (!context) return "";
  const image = context.createImageData(map.textureWidth, map.textureHeight);
  image.data.set(map.toRgbaBytes());
  context.putImageData(image, 0, 0);
  const dataUrl = canvas.toDataURL("image/png");
  dataUrls.set(map.key, dataUrl);
  return dataUrl;
}

function publishDescriptors(): void {
  descriptors.value = Object.freeze(
    Array.from(runtimeEntries.values(), (entry) =>
      Object.freeze({
        key: entry.key,
        filterId: entry.filterId,
        dataUrl: entry.dataUrl,
        displacement: entry.displacement,
        references: entry.references,
      }),
    ),
  );
}

export function acquireRuntimeGlassFilter(
  request: NormalMapRequest,
  displacement: number,
): RuntimeGlassFilterLease {
  const lease = registry.acquire(request);
  const dataUrl = normalMapDataUrl(lease.map);
  const runtimeKey = `${lease.key}:d${displacement}`;
  const current = runtimeEntries.get(runtimeKey);
  const filterId = `${lease.filterId}-d${displacement}`;
  const entry: RuntimeGlassFilterEntry = Object.freeze({
    key: runtimeKey,
    filterId,
    dataUrl,
    displacement,
    references: (current?.references ?? 0) + 1,
    generation: current?.generation ?? Symbol(runtimeKey),
  });
  runtimeEntries.set(runtimeKey, entry);
  publishDescriptors();
  let released = false;
  return Object.freeze({
    ...lease,
    key: runtimeKey,
    filterId,
    dataUrl,
    release() {
      if (released) return;
      released = true;
      lease.release();
      const active = runtimeEntries.get(runtimeKey);
      if (active?.generation !== entry.generation) return;
      if (active?.references === 1) {
        runtimeEntries.delete(runtimeKey);
      } else if (active) {
        runtimeEntries.set(runtimeKey, Object.freeze({
          ...active,
          references: active.references - 1,
        }));
      }
      publishDescriptors();
    },
  });
}

export function useGlassFilterDescriptors(): DeepReadonly<
  Ref<readonly RenderableGlassFilter[]>
> {
  return readonly(descriptors);
}

export function resetGlassFilterRuntimeForTests(): void {
  registry.clear();
  runtimeEntries.clear();
  dataUrls.clear();
  descriptors.value = EMPTY_DESCRIPTORS;
}
