import { writeFile } from 'node:fs/promises';

const source = 'https://api.postpeer.dev/docs/openapi.json';
const response = await fetch(source);
if (!response.ok) {
  throw new Error(`Unable to fetch ${source}: ${response.status} ${response.statusText}`);
}
const specification = await response.json();
await writeFile(new URL('../openapi.json', import.meta.url), `${JSON.stringify(specification, null, 2)}\n`);
console.log(`Updated openapi.json from ${source}`);
