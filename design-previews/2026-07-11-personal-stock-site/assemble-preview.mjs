import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
let html = fs.readFileSync(path.join(root, 'shell.html'), 'utf8');

for (const id of ['a', 'b', 'c', 'd']) {
  const fragment = fs.readFileSync(path.join(root, 'fragments', `${id}.html`), 'utf8');
  html = html.replace(`<!--DIR_${id.toUpperCase()}-->`, fragment);
}

fs.writeFileSync(path.join(root, 'index.html'), html, 'utf8');
