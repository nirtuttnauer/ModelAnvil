import { readFile, writeFile } from 'node:fs/promises';

// Native FigCraft variables are the source of truth. CSS lengths need units;
// React's persisted theme/density values use lowercase mode names.
const source = new URL('../../design/figcraft/variables.json', import.meta.url);
const output = new URL('../src/design-system/tokens.css', import.meta.url);
const { meta } = JSON.parse(await readFile(source, 'utf8'));
const name = value => value.toLowerCase().replace(/[^a-z0-9]+/g, '-');
const value = (variable, modeId) => {
  const v = variable.valuesByMode[modeId];
  if (variable.resolvedType === 'COLOR') {
    const hex = channel => Math.round(channel * 255).toString(16).padStart(2, '0');
    return `#${hex(v.r)}${hex(v.g)}${hex(v.b)}${v.a === 1 ? '' : hex(v.a)}`;
  }
  if (variable.resolvedType === 'FLOAT') return `${v}px`;
  return JSON.stringify(v);
};
const blocks = Object.values(meta.variableCollections).flatMap(collection =>
  collection.modes.map(mode => {
    const selector = mode.modeId === collection.defaultModeId
      ? ':root' : `:root[data-${name(collection.name)}="${name(mode.name)}"]`;
    const declarations = collection.variableIds.map(id => {
      const variable = meta.variables[id];
      return `  --${name(variable.name)}: ${value(variable, mode.modeId)};`;
    });
    return `/* ${collection.name} · ${mode.name} */\n${selector} {\n${declarations.join('\n')}\n}`;
  })
);
const css = `/* Generated from design/figcraft/variables.json. Run npm run tokens:sync. */\n${blocks.join('\n\n')}\n`;
if (process.argv.includes('--check')) {
  if (await readFile(output, 'utf8').catch(() => '') !== css) {
    throw new Error('FigCraft tokens changed. Run npm run tokens:sync and commit the generated CSS.');
  }
} else {
  await writeFile(output, css);
}
