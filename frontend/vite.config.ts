import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      // main.tsx only mounts the app into the page.
      exclude: ["src/**/*.test.{ts,tsx}", "src/main.tsx"],
      reporter: ["text"],
      thresholds: { lines: 90, functions: 90, branches: 90, statements: 90 },
    },
  },
});
