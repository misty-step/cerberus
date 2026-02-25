#!/usr/bin/env node

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const readline = require('node:readline');

const TEMPLATE_PATH = path.join(__dirname, '../templates/consumer-workflow-reusable.yml');
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

function readApiKeySource() {
  const envKey = process.env.CERBERUS_OPENROUTER_API_KEY || process.env.OPENROUTER_API_KEY;
  if (envKey && envKey.trim()) {
    return { kind: 'env', value: envKey.trim() };
  }

  if (!process.stdin.isTTY) {
    fail('No API key in CERBERUS_OPENROUTER_API_KEY (or OPENROUTER_API_KEY) and no interactive TTY available for gh prompt.');
  }

  return { kind: 'prompt' };
}

async function promptApiKeyOnce() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: true,
  });

  try {
    const value = await new Promise((resolve) => {
      rl.question('Enter Cerberus OpenRouter API key: ', resolve);
    });

    if (!value || !value.trim()) {
      fail('No API key entered.');
    }
    return value.trim();
  } finally {
    rl.close();
  }
}

async function readTemplate() {
  return fs.promises.readFile(TEMPLATE_PATH, 'utf8');
}

function writeWorkflow(repoRoot, template) {
  const dest = path.join(repoRoot, DEST_PATH);
  const dir = path.dirname(dest);
  fs.mkdirSync(dir, { recursive: true });

  if (!fs.existsSync(dest)) {
    fs.writeFileSync(dest, template);
    return { changed: true, skipped: false, dest, workflowContent: template };
  }

  const existing = fs.readFileSync(dest, 'utf8');
  if (existing.trim() === template.trim()) {
    return { changed: false, skipped: false, dest, workflowContent: existing };
  }

  return { changed: false, skipped: true, dest, workflowContent: existing };
}

function setSecret(repoRoot, keySource, secretName) {
  const args = ['secret', 'set', secretName];
  const isEnv = keySource.kind === 'env';
  const options = {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: [isEnv ? 'pipe' : 'inherit', 'inherit', 'pipe'],
  };

  if (isEnv) {
    options.input = keySource.value;
  }

  const result = spawnSync('gh', args, options);

  if (result.status !== 0) {
    const message =
      result.stderr && result.stderr.trim()
        ? result.stderr.trim()
        : 'gh secret set failed.';
    fail(`Failed to set ${secretName} in repository secrets: ${message}`);
  }
}

async function initCommand() {
  requireBinary('git');
  requireBinary('gh');

  const repoRoot = getRepoRoot();
  const initialKeySource = readApiKeySource();
  const keySource =
    initialKeySource.kind === 'prompt'
      ? { kind: 'env', value: await promptApiKeyOnce() }
      : initialKeySource;
  const template = await readTemplate();
  const { changed, skipped, dest, workflowContent } = writeWorkflow(repoRoot, template);

  setSecret(repoRoot, keySource, 'CERBERUS_OPENROUTER_API_KEY');

  let mirroredLegacySecret = false;
  if (skipped && /secrets\.OPENROUTER_API_KEY/.test(workflowContent)) {
    setSecret(repoRoot, keySource, 'OPENROUTER_API_KEY');
    mirroredLegacySecret = true;
  }

  if (changed) {
    process.stdout.write(`Created ${path.relative(repoRoot, dest)}\n`);
  } else if (skipped) {
    process.stdout.write(`Left unchanged: ${path.relative(repoRoot, dest)} (existing file differs from template)\n`);
  } else {
    process.stdout.write(`Up-to-date: ${path.relative(repoRoot, dest)}\n`);
  }

  process.stdout.write('Configured CERBERUS_OPENROUTER_API_KEY as GitHub Actions secret.\n');
  if (mirroredLegacySecret) {
    process.stdout.write('Existing workflow references OPENROUTER_API_KEY; mirrored that legacy secret for compatibility.\n');
  }
  if (changed) {
    process.stdout.write('Run: git add .github/workflows/cerberus.yml && git commit -m "Add Cerberus workflow"\n');
  } else {
    process.stdout.write('No workflow file changes to commit.\n');
  }
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
