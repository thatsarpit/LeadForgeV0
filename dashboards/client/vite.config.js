import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs';
import path from 'path';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
  },
  preview: {
    allowedHosts: ['app.engyne.space', 'localhost', '127.0.0.1'],
    host: true,
  },
})
