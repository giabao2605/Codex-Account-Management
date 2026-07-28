import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

const backendOrigin = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: backendOrigin,
        changeOrigin: true,
        configure(proxy) {
          proxy.on("proxyReq", (proxyRequest) => {
            proxyRequest.setHeader("origin", backendOrigin);
          });
        },
      },
    },
  },
  build: {
    outDir: "../web-dist",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    rolldownOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.replaceAll("\\", "/");
          if (
            normalizedId.includes("/node_modules/vue/")
            || normalizedId.includes("/node_modules/@vue/")
            || normalizedId.includes("/node_modules/pinia/")
          ) {
            return "vue-core";
          }
          return undefined;
        },
      },
    },
  },
});
