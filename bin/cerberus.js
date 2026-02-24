#!/usr/bin/env node

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const TEMPLATE_PATH = path.join(__dirname, '../templates/consumer-workflow.yml');
const DEST_PATH = path.join('.github', 'workflows', 'cerberus.yml');

const command = process.argv[2];

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function runCommand(commandName, args, options = {}) {
  const result = spawnSync(commandName, args, {
    cwd: options.cwd,
    encoding: 'utf8',
    stdio: 'pipe',
  });

  if (result.error) {
    return { status: 1 };
  }

  return result;
}

function requireBinary(binary, args = ['--version']) {
  const result = runCommand(binary, args);
  if (result.status !== 0) {
    fail(`${binary} is required and was not found or not executable.`);
  }
}

function getRepoRoot() {
  const result = runCommand('git', ['rev-parse', '--show-toplevel']);
  if (result.status !== 0) {
    fail('This command must run inside a git repository.');
  }
  return result.stdout.trim();
}

function readApiKey() {
  const envKey = process.env.OPENROUTER_API_KEY;
  if (envKey && envKey.trim()) {
    return envKey.trim();
  }

  if (!process.stdin.isTTY) {
    fail('No API key in OPENROUTER_API_KEY and no interactive TTY available for gh prompt.');
  }

  return '';
}

async function readTemplate() {
  return fs.promises.readFile(TEMPLATE_PATH, 'utf8');
}

function writeWorkflow(repoRoot, template) {
  const dest = path.join(repoRoot, DEST_PATH);
  const dir = path.dirname(dest);
  fs.mkdirSync(dir, { recursive: true });

  const existing = fs.existsSync(dest) ? fs.readFileSync(dest, 'utf8') : '';
  if (existing.trim() === template.trim()) {
    return { changed: false, dest };
  }

  fs.writeFileSync(dest, template);
  return { changed: true, dest };
}

function setSecret(repoRoot, key) {
  const args = ['secret', 'set', 'OPENROUTER_API_KEY'];
  const options = {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: ['inherit', 'inherit', 'pipe'],
  };

  if (key) {
    args.push('--body', key);
  }

  const result = spawnSync('gh', args, options);

  if (result.status !== 0) {
    const message =
      result.stderr && result.stderr.trim()
        ? result.stderr.trim()
        : 'gh secret set failed.';
    fail(`Failed to set OPENROUTER_API_KEY in repository secrets: ${message}`);
  }
}

async function initCommand() {
  requireBinary('git');
  requireBinary('gh');

  const repoRoot = getRepoRoot();
  const template = await readTemplate();
  const { changed, dest } = writeWorkflow(repoRoot, template);

  const key = await readApiKey();
  setSecret(repoRoot, key);

  if (changed) {
    process.stdout.write(`Created ${path.relative(repoRoot, dest)}\n`);
  } else {
    process.stdout.write(`Up-to-date: ${path.relative(repoRoot, dest)}\n`);
  }

  process.stdout.write('Configured OPENROUTER_API_KEY as GitHub Actions secret.\n');
  process.stdout.write('Run: git add .github/workflows/cerberus.yml && git commit -m "Add Cerberus workflow"\n');
}

async function main() {
  if (!command || command === '--help' || command === '-h') {
    process.stdout.write('Usage: cerberus init\n');
    return;
  }

  if (command !== 'init') {
    fail(`Unknown command: ${command}. Usage: cerberus init`);
  }

  await initCommand();
}

main().catch((error) => fail(error.message));
