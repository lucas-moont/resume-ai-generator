#!/usr/bin/env node
// One-time project setup: creates the backend venv, installs Python deps, installs the
// Playwright Chromium browser, installs frontend deps, and seeds optional local files
// (.env, data/profile/resume.json) from their examples when missing. Run: `npm run setup`.
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const apiDir = path.join(root, 'apps', 'api');
const webDir = path.join(root, 'apps', 'web');
const isWin = process.platform === 'win32';

function run(label, command, args, cwd) {
  console.log(`\n> ${label}`);
  const result = spawnSync(command, args, { cwd, stdio: 'inherit' });
  if (result.status !== 0) {
    console.error(`\nFalhou: ${label} (código ${result.status})`);
    process.exit(result.status ?? 1);
  }
}

const venvDir = path.join(apiDir, '.venv');
const venvPython = isWin
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python');

if (!existsSync(venvPython)) {
  run('criar venv (apps/api/.venv)', isWin ? 'python' : 'python3', ['-m', 'venv', '.venv'], apiDir);
} else {
  console.log('\n✓ venv já existe em apps/api/.venv, pulando criação');
}

run('pip install -r requirements.txt', venvPython, ['-m', 'pip', 'install', '-r', 'requirements.txt'], apiDir);
run('playwright install chromium', venvPython, ['-m', 'playwright', 'install', 'chromium'], apiDir);
run(
  'npm install (apps/web)',
  isWin ? 'cmd.exe' : 'npm',
  isWin ? ['/c', 'npm', 'install'] : ['install'],
  webDir
);

const envPath = path.join(root, '.env');
const envExamplePath = path.join(root, '.env.example');
if (!existsSync(envPath) && existsSync(envExamplePath)) {
  copyFileSync(envExamplePath, envPath);
  console.log('\n✓ .env criado a partir de .env.example — edite se for usar chaves de API');
} else if (existsSync(envPath)) {
  console.log('\n✓ .env já existe');
}

const profileDir = path.join(root, 'data', 'profile');
const resumeJsonPath = path.join(profileDir, 'resume.json');
const resumeExamplePath = path.join(root, 'data', 'examples', 'profile', 'resume.example.json');
if (!existsSync(resumeJsonPath) && existsSync(resumeExamplePath)) {
  mkdirSync(profileDir, { recursive: true });
  copyFileSync(resumeExamplePath, resumeJsonPath);
  console.log(
    '\n✓ data/profile/resume.json criado a partir do exemplo — EDITE com seus dados reais antes de usar o app'
  );
} else if (existsSync(resumeJsonPath)) {
  console.log('\n✓ data/profile/resume.json já existe');
}

console.log(
  '\nSetup concluído.\n' +
  '  - Rode `npm run dev` para subir API + UI.\n' +
  '  - Opcional (testes/pre-commit): pip install -r apps/api/requirements-dev.txt (dentro do venv) e pre-commit install.\n'
);
