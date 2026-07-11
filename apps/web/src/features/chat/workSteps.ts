export const WORK_STEPS = [
  // v4, F3: heartbeat step for the Analysis/Proposal Turn (typing dots on the
  // frontend, never the ProgressCard — spec §3.5) — listed here for the same
  // reason as the generation steps below, not because it's part of that pipeline.
  { id: 'analyzing_job', label: 'Analyzing job description' },
  { id: 'preparing_context', label: 'Preparing context' },
  { id: 'extracting_profile_pdf', label: 'Extracting profile from PDF' },
  { id: 'calling_ai', label: 'Calling AI model' },
  { id: 'validating_response', label: 'Validating response' },
  { id: 'finalizing', label: 'Finalizing' },
] as const
