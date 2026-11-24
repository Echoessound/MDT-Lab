#!/usr/bin/env node
/**
 * Automated UI, CSS Grid, and Animation Guardrail (emilkowalski/skills + MDT Lab Spec).
 * Zero external dependencies. Runs in <50ms as part of `npm run lint:ui` and `npm run check`.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const srcDir = join(root, 'src');

function walk(dir, exts) {
  const files = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) files.push(...walk(full, exts));
    else if (exts.some(ext => full.endsWith(ext))) files.push(full);
  }
  return files;
}

const violations = [];

for (const file of walk(srcDir, ['.css'])) {
  const rel = relative(root, file);
  // Preserve line numbers while blanking out block comments.
  const content = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '));
  const lines = content.split('\n');
  const isModernScope = rel.includes('console/') || rel.includes('research/');

  lines.forEach((line, i) => {
    const lineNo = i + 1;
    if (/transition\s*:\s*[^;]*\ball\b/i.test(line)) {
      violations.push(`${rel}:${lineNo} — Banned "transition: all". Specify exact composite/color properties.`);
    }
    if (/\bease-in\b(?![-a-z])/i.test(line)) {
      violations.push(`${rel}:${lineNo} — Banned "ease-in" curve (sluggish start). Use custom ease-out/sheet bezier.`);
    }
    if (isModernScope && /transition\s*:[^;]*\b(width|height|grid-template-columns)\b/i.test(line)) {
      violations.push(`${rel}:${lineNo} — Banned layout-thrashing transition (width/height/grid-template-columns). Animate transform (scaleX/translate3d) instead.`);
    }
    if (isModernScope && /#(173e35|185941|14543c|d5e8a1)\b/i.test(line)) {
      violations.push(`${rel}:${lineNo} — Legacy dark-green hex detected; use iOS semantic tokens.`);
    }
  });
}

for (const file of walk(srcDir, ['.tsx'])) {
  const rel = relative(root, file);
  const content = readFileSync(file, 'utf8');
  let cursor = 0;
  while ((cursor = content.indexOf('style={{', cursor)) !== -1) {
    const startObj = cursor + 'style={'.length;
    let depth = 0;
    let endObj = startObj;
    for (; endObj < content.length; endObj++) {
      if (content[endObj] === '{') depth++;
      else if (content[endObj] === '}') {
        depth--;
        if (depth === 0) break;
      }
    }
    const body = content.slice(startObj + 1, endObj);
    const lineNo = content.slice(0, cursor).split('\n').length;
    cursor = endObj + 1;
    const keys = [...body.matchAll(/(?:['"](--[A-Za-z0-9_-]+)['"]|\b([A-Za-z][A-Za-z0-9_]*))\s*:/g)]
      .map(m => m[1] || m[2]);
    const nonCustomKeys = keys.filter(k => !k.startsWith('--'));
    if (nonCustomKeys.length > 0) {
      violations.push(
        `${rel}:${lineNo} — Banned inline layout/box style (${nonCustomKeys.join(', ')}). Use semantic CSS Grid classes; only '--*' CSS custom properties are allowed in style={{}}.`
      );
    }
  }
}

if (violations.length > 0) {
  console.error(`UI & Architecture Guardrail failed with ${violations.length} violation(s):\n`);
  for (const v of violations) console.error(`  ✕ ${v}`);
  process.exit(1);
}

console.log('✓ UI & CSS Grid standards verified (0 violations across src/).');
