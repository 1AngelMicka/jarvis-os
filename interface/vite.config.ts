import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Interface servie sur 127.0.0.1:5174 en développement ; l'API du Core (127.0.0.1:8765) passe par le proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: { "/v1": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
  preview: { host: "127.0.0.1", port: 4174, strictPort: true },
  build: { outDir: "dist", sourcemap: true },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
