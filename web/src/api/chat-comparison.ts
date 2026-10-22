import type { ChatMessage, LocalModel } from './inference.ts';

export function trainedChatModels(models: LocalModel[]): LocalModel[] {
  return models.filter(model => !!model.training_run_id || !!model.base_model_id);
}
export function matchedBaseModel(model: LocalModel | undefined, models: LocalModel[]): LocalModel | undefined {
  return model?.base_model_id && model.base_model_id !== model.id ? models.find(base => base.id === model.base_model_id) : undefined;
}
export function comparisonInput(history: ChatMessage[], freshContext: boolean): ChatMessage[] {
  if (!freshContext) return history;
  const last = [...history].reverse().find(message => message.role === 'user');
  return last ? [last] : [];
}
export function sharedOutputLimit(first: LocalModel | undefined, second: LocalModel | undefined): number {
  return Math.min(first?.max_tokens || 256, second?.max_tokens || 256,
    Math.max(1, (first?.context_limit || 2048) - 8), Math.max(1, (second?.context_limit || 2048) - 8));
}
