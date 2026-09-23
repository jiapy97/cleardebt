import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "#e4e4e7",
        muted: "#71717a",
      },
    },
  },
  plugins: [],
} satisfies Config;
