import {
  NormalMapCache,
  type NormalMap,
  type NormalMapRequest,
} from "./normalMap.ts";

export interface GlassFilterLease {
  readonly key: string;
  readonly filterId: string;
  readonly map: NormalMap;
  release(): void;
}

export interface GlassFilterDescriptor {
  readonly key: string;
  readonly filterId: string;
  readonly map: NormalMap;
  readonly references: number;
}

interface RegistryEntry {
  readonly filterId: string;
  readonly map: NormalMap;
  readonly references: number;
  readonly generation: symbol;
}

function filterIdFromKey(key: string): string {
  return `liquid-glass-v3-${key.replaceAll(/[^a-zA-Z0-9_-]/g, "-")}`;
}

export class GlassFilterRegistry {
  readonly #cache: NormalMapCache;
  readonly #entries = new Map<string, RegistryEntry>();

  constructor(cache = new NormalMapCache()) {
    this.#cache = cache;
  }

  get size(): number {
    return this.#entries.size;
  }

  getReferenceCount(key: string): number {
    return this.#entries.get(key)?.references ?? 0;
  }

  snapshot(): readonly GlassFilterDescriptor[] {
    return Object.freeze(
      Array.from(this.#entries, ([key, entry]) =>
        Object.freeze({
          key,
          filterId: entry.filterId,
          map: entry.map,
          references: entry.references,
        }),
      ),
    );
  }

  acquire(request: NormalMapRequest): GlassFilterLease {
    const map = this.#cache.get(request);
    const current = this.#entries.get(map.key);
    const entry: RegistryEntry = current
      ? Object.freeze({
          ...current,
          references: current.references + 1,
        })
      : Object.freeze({
          filterId: filterIdFromKey(map.key),
          map,
          references: 1,
          generation: Symbol(map.key),
        });
    this.#entries.set(map.key, entry);

    let released = false;
    return Object.freeze({
      key: map.key,
      filterId: entry.filterId,
      map,
      release: () => {
        if (released) {
          return;
        }
        released = true;
        this.#release(map.key, entry.generation);
      },
    });
  }

  clear(): void {
    this.#entries.clear();
  }

  #release(key: string, generation: symbol): void {
    const current = this.#entries.get(key);
    if (!current || current.generation !== generation) {
      return;
    }
    if (current.references === 1) {
      this.#entries.delete(key);
      return;
    }
    this.#entries.set(
      key,
      Object.freeze({
        ...current,
        references: current.references - 1,
      }),
    );
  }
}
