import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/ai_tools_hunter/static",
    emptyOutDir: true,
  },
});
