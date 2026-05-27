export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: "#0a0a0a", 50: "#0e0e0e", 100: "#121212", 200: "#181818", 300: "#222222" },
        border: { DEFAULT: "#1f1f1f", strong: "#2a2a2a", subtle: "#161616" },
        fg: { DEFAULT: "#ededed", muted: "#9b9b9b", subtle: "#6b6b6b", faint: "#454545" },
        accent: { DEFAULT: "#7c7cff", hover: "#9090ff", dim: "#5757d4" },
        ok: "#3fb950", warn: "#d29922", err: "#f85149", info: "#58a6ff",
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "Inter", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "monospace"],
      },
    },
  },
};
