#!/usr/bin/env node
// Sobe só a API (uvicorn), usada por `npm run dev:api` na raiz.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const apiDir = path.join(root, 'apps', 'api');

const venvPython = process.platform === 'win32'
  ? path.join(apiDir, '.venv', 'Scripts', 'python.exe')
  : path.join(apiDir, '.venv', 'bin', 'python');

if (!existsSync(venvPython)) {
  console.error(
    `\nVenv do backend não encontrado em:\n  ${venvPython}\n\n` +
    'Rode a configuração inicial (README.md > Setup > 2) Backend).\n'
  );
  process.exit(1);
}

const result = spawnSync(
  venvPython,
  ['-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000'],
  { cwd: apiDir, stdio: 'inherit' }
);
process.exit(result.status ?? 1);
