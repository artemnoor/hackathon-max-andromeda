import { defineConfig } from 'vite';

export default defineConfig({
  // This plain CSS app has no PostCSS transforms; keep machine-level config from leaking in.
  css: {
    postcss: {
      plugins: [],
    },
  },
  build: { manifest: true },
});
