import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Fixture minimo para o Agent Driven Mode reconhecer React + Vite.
export default defineConfig({
  plugins: [react()],
});
