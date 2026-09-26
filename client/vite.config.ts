import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// dev server proxies to the python table server (run.py) on 8770
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8770",
      "/ws": { target: "ws://localhost:8770", ws: true },
    },
  },
});
