import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  root: "frontend",
  base: "/static/dist/",
  plugins: [react(), tailwindcss()],
  build: { outDir: "../osint_picture/static/dist", emptyOutDir: true },
});
