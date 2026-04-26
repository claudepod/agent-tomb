import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://www.agentmemorial.com",
  vite: {
    plugins: [tailwindcss()],
  },
});
