<script setup lang="ts">
withDefaults(defineProps<{ message?: string }>(), {
  message: "Mất kết nối với ứng dụng local. Dữ liệu sẽ tự cập nhật khi kết nối trở lại.",
});
</script>

<template>
  <section
    class="offline-banner standard-surface"
    data-material="standard"
    role="alert"
  >
    <strong>Mất kết nối</strong>
    <span>{{ message }}</span>
  </section>
</template>
