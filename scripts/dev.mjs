#!/usr/bin/env node
// Sobe API (uvicorn) + Web (vite) com um único comando: `npm run dev` na raiz.
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const apiDir = path.join(root, 'apps', 'api');
const webDir = path.join(root, 'apps', 'web');

const venvPython = process.platform === 'win32'
  ? path.join(apiDir, '.venv', 'Scripts', 'python.exe')
  : path.join(apiDir, '.venv', 'bin', 'python');

if (!existsSync(venvPython)) {
  console.error(
    `\nVenv do backend não encontrado em:\n  ${venvPython}\n\n` +
    'Rode a configuração inicial (README.md > Setup > 2) Backend):\n' +
    '  cd apps/api\n' +
    '  python -m venv .venv\n' +
    '  .venv\\Scripts\\activate          (Windows)  ou  source .venv/bin/activate  (macOS/Linux)\n' +
    '  pip install -r requirements.txt\n' +
    '  playwright install chromium\n'
  );
  process.exit(1);
}

if (!existsSync(path.join(webDir, 'node_modules'))) {
  console.error(
    '\nDependências do frontend não instaladas.\n' +
    'Rode:\n  cd apps/web\n  npm install\n'
  );
  process.exit(1);
}

const api = spawn(
  venvPython,
  ['-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000'],
  { cwd: apiDir, stdio: 'inherit' }
);

const web = spawn(
  process.platform === 'win32' ? 'cmd.exe' : 'npm',
  process.platform === 'win32' ? ['/c', 'npm', 'run', 'dev'] : ['run', 'dev'],
  { cwd: webDir, stdio: 'inherit' }
);

let shuttingDown = false;
function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  api.kill();
  web.kill();
  process.exitCode = code ?? 0;
}

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));
api.on('exit', (code) => {
  if (!shuttingDown) {
    console.error(`\n[api] processo encerrou (code ${code})`);
    shutdown(code ?? 1);
  }
});
web.on('exit', (code) => {
  if (!shuttingDown) {
    console.error(`\n[web] processo encerrou (code ${code})`);
    shutdown(code ?? 1);
  }
});
