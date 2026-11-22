#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const [command, name, ...rest] = process.argv.slice(2);
if (command !== 'init' || rest.length || name === '--help' || name === '-h') {
  console.error('Uso: npx subtitle-studio init [directorio]');
  process.exit(command === '--help' || command === '-h' || name === '--help' || name === '-h' ? 0 : 1);
}

const target = path.resolve(name || 'subtitle-studio');
try {
  fs.mkdirSync(target);
} catch (error) {
  if (error.code === 'EEXIST') console.error('El directorio ya existe; elige otro. No se ha sobrescrito nada.');
  else console.error(`No se pudo crear el directorio: ${error.message}`);
  process.exit(1);
}

// Only copy known source files, even when invoked from a development checkout.
const groups = {
  backend: ['Dockerfile', '.dockerignore', 'requirements.txt'],
  'backend/app': fs.readdirSync(path.join(root, 'backend/app')).filter(x => x.endsWith('.py')),
  frontend: fs.readdirSync(path.join(root, 'frontend')).filter(x => /\.(js|html|conf)$/.test(x) || ['Dockerfile', '.dockerignore'].includes(x)),
  'mac-worker': fs.readdirSync(path.join(root, 'mac-worker')).filter(x => x.endsWith('.py') || x === 'requirements.txt'),
  scripts: fs.readdirSync(path.join(root, 'scripts')).filter(x => /\.(py|sh)$/.test(x)),
  docs: ['LOCAL-FILES.md', 'MVP-VALIDATION.md'],
  tests: fs.readdirSync(path.join(root, 'tests')).filter(x => /\.(py|cjs)$/.test(x)),
  bin: ['subtitle-studio.cjs'],
  templates: ['gitignore'],
};
try {
  for (const file of ['README.md', 'LICENSE', '.env.example', 'docker-compose.yml', 'package.json', 'pytest.ini', 'requirements-dev.txt']) {
    fs.copyFileSync(path.join(root, file), path.join(target, file), fs.constants.COPYFILE_EXCL);
  }
  fs.copyFileSync(path.join(root, 'templates', 'gitignore'), path.join(target, '.gitignore'), fs.constants.COPYFILE_EXCL);
  for (const [dir, files] of Object.entries(groups)) {
    fs.mkdirSync(path.join(target, dir), { recursive: true });
    for (const file of files) {
      const source = path.join(root, dir, file);
      if (!fs.lstatSync(source).isFile()) continue;
      fs.copyFileSync(source, path.join(target, dir, file), fs.constants.COPYFILE_EXCL);
    }
  }
  fs.mkdirSync(path.join(target, 'data'));
} catch (error) {
  console.error(`No se completó la preparación en ${target}: ${error.message}. Se conservan los archivos creados para revisión.`);
  process.exit(1);
}
console.log(`Proyecto preparado en ${target}\nSigue las instrucciones del README: macOS Apple Silicon, Docker, FFmpeg y Ollama.`);
