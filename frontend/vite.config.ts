import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The SPA is served from CloudFront; /api is a same-origin behaviour routed to
// the ALB, so there are no CORS concerns. In local development we proxy /api to
// the FastAPI control-plane.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/healthz": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
