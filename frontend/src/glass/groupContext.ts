import {
  inject,
  onBeforeUnmount,
  onMounted,
  shallowReadonly,
  shallowRef,
  type InjectionKey,
  type Ref,
} from "vue";

export interface GlassGroupContext {
  readonly groupId: Readonly<Ref<string>>;
  readonly mergeDistance: Readonly<Ref<number>>;
  readonly members: Readonly<Ref<readonly HTMLElement[]>>;
  register: (element: HTMLElement) => () => void;
}

export const GLASS_GROUP_KEY: InjectionKey<GlassGroupContext> = Symbol(
  "otp-liquid-glass-group",
);

export function createGlassGroupContext(
  groupId: Readonly<Ref<string>>,
  mergeDistance: Readonly<Ref<number>>,
): GlassGroupContext {
  const members = shallowRef<readonly HTMLElement[]>([]);
  return {
    groupId,
    mergeDistance,
    members: shallowReadonly(members),
    register(element) {
      if (!members.value.includes(element)) {
        members.value = Object.freeze([...members.value, element]);
      }
      return () => {
        members.value = Object.freeze(
          members.value.filter((member) => member !== element),
        );
      };
    },
  };
}

export function useGlassGroupMember(
  element: Readonly<Ref<HTMLElement | null>>,
): GlassGroupContext | null {
  const context = inject(GLASS_GROUP_KEY, null);
  let unregister: (() => void) | null = null;
  onMounted(() => {
    if (context && element.value) unregister = context.register(element.value);
  });
  onBeforeUnmount(() => unregister?.());
  return context;
}
