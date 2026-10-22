export function modelDisplayName(name: string): string {
  const managed = /^Managed (SmolLM2-(?:135M|1\.7B)-Instruct) · [a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.exec(name);
  if (managed) return managed[1].replace('-Instruct', ' Instruct');
  const guided = /^smollm2-gpu-sft-([a-f0-9]{8})-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.exec(name);
  return guided ? `SmolLM2 fine-tune · ${guided[1]}` : name;
}

export function referenceInputError(model: { format: string; tokenizer_kind?: string; context_limit?: number } | undefined, messages: { role: string; content: string }[], maxTokens: number, temperature: number, format: string): string | null {
  if (model?.format !== 'cpu-reference') return null;
  if (messages.length !== 1 || messages[0].role !== 'user') return 'This CPU reference accepts one user prompt. Start a new conversation without a system prompt.';
  if (temperature !== 0 || format === 'chatml' || !Number.isInteger(maxTokens) || maxTokens < 1 || maxTokens > 32) return 'CPU references support greedy decoding, plain text and 1–32 output tokens.';
  if (!model.tokenizer_kind || !model.context_limit) return null;
  const inputTokens = (model.tokenizer_kind === 'byte-v1' ? new TextEncoder().encode(messages[0].content).length : [...messages[0].content].length) + 2;
  return inputTokens + maxTokens > model.context_limit ? `Prompt uses ${inputTokens} tokens; reserve ${maxTokens} output tokens within the ${model.context_limit}-token context.` : null;
}
