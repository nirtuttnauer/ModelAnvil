export interface ModelFileRef { artifact_id: string; sha256: string; byte_size: number }
export function savedModelFiles(raw: string): Record<string, ModelFileRef> {
  try {
    const files = JSON.parse(raw);
    if (!files || typeof files !== 'object' || Array.isArray(files) || Object.keys(files).length > 64) return {};
    for (const [name, ref] of Object.entries(files) as [string, ModelFileRef][]) {
      if (!/^[a-zA-Z0-9_.-]{1,180}$/.test(name) || name === '..' || !ref ||
        !/^[0-9a-f-]{36}$/i.test(ref.artifact_id) || !/^[0-9a-f]{64}$/i.test(ref.sha256) ||
        !Number.isSafeInteger(ref.byte_size) || ref.byte_size <= 0 || ref.byte_size > 8 * 1024**3 ||
        Object.keys(ref).some(key => !['artifact_id', 'sha256', 'byte_size'].includes(key))) return {};
    }
    return files;
  } catch { return {}; }
}
export function validateModelFiles(files: { name: string; size: number }[], verified: Record<string, ModelFileRef>): void {
  const names = [...Object.keys(verified), ...files.map(file => file.name)];
  if (names.length > 64 || new Set(names).size !== names.length) throw new Error('A selected filename is already verified or duplicated. Remove its saved reference before replacing it.');
  if (files.some(file => !/^[a-zA-Z0-9_.-]{1,180}$/.test(file.name) || file.name === '..' || file.size <= 0 || file.size > 8 * 1024**3)) throw new Error('Use supported filenames of 1 byte–8 GiB.');
  if (files.reduce((sum, file) => sum + file.size, 0) + Object.values(verified).reduce((sum, ref) => sum + ref.byte_size, 0) > 8 * 1024**3) throw new Error('A snapshot supports at most 8 GiB total, including previously verified files.');
  if (names.length === 1 && names[0].endsWith('.gguf')) return;
  if (!names.includes('config.json') || !names.some(name => name.endsWith('.safetensors')) ||
      !(names.includes('tokenizer.json') || names.includes('tokenizer.model') || (names.includes('vocab.json') && names.includes('merges.txt')))) {
    throw new Error('A snapshot requires weights, config.json and tokenizer assets before upload.');
  }
}
