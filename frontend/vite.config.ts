import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Built output lands in cleardebt/static/console and is served by FastAPI
// at /static/console/* with the console itself mounted at /.
export default defineConfig({
  base: "/static/console/",
  build: {
    outDir: "../cleardebt/static/console",
    emptyOutDir: true,
  },
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "^/(api|issues|controls|sessions|mrs|batch|setup|switches|schedule|project-switches)": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
