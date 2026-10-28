const examples: Record<string, string[]> = {
  billing: ['I was charged twice this month.', 'Please send an invoice for my last payment.', 'How can I change my payment card?', 'I need a refund for an accidental purchase.', 'Why did my subscription price change?', 'My payment was declined.', 'Can I switch to annual billing?', 'The invoice has the wrong company name.', 'When is my next payment due?', 'I cancelled but received another charge.'],
  access: ['I forgot my password.', 'My sign-in code never arrived.', 'Please add my colleague to our workspace.', 'I cannot log in with my email address.', 'How do I reset two-factor authentication?', 'My invitation link expired.', 'I need to remove a former team member.', 'My account says it is locked.', 'How can I change the email used to sign in?', 'I signed in but cannot access our project.'],
  technical: ['The app crashes when I upload a file.', 'My report download is empty.', 'The page stays blank after refreshing.', 'Search returns an error for every query.', 'The export button stops responding.', 'My saved changes disappeared.', 'The progress indicator has been stuck for an hour.', 'Images do not load in the preview.', 'The browser shows a server error.', 'The file preview shows corrupted text.'],
};

export const classificationLabels = Object.keys(examples);
export const classificationStarter = Object.entries(examples).flatMap(([label, texts]) => texts.map((text, index) => ({
  prompt: `Classify the support request. Reply with exactly one label: billing, access, technical.\nRequest: ${text}`,
  response: label, group_id: `starter-${label}-${index + 1}`,
})));

export function classificationStarterCsv(): string {
  const quote = (value: string) => `"${value.replaceAll('"', '""')}"`;
  return 'prompt,response,group_id\n' + classificationStarter.map(row => [row.prompt, row.response, row.group_id].map(quote).join(',')).join('\n') + '\n';
}
