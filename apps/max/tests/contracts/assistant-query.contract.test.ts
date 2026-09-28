import type { components, paths } from '../../src/andromeda/generated/public-api.js';

type AssistantQuery = NonNullable<paths['/api/v1/assistant/query']['post']>['requestBody'] extends infer Body
  ? Body extends { content: { 'application/json': infer Request } }
    ? Request
    : never
  : never;

const assistantQuery: AssistantQuery = {
  text: 'What programs include applied mathematics?',
  sessionId: 'query-session:00000000000000000000000000000000',
  expectedRevision: 1,
};

const assistantResult: components['schemas']['AssistantResult'] = {
  state: 'complete',
  session_id: 'query-session:00000000000000000000000000000000',
  revision: 1,
  options: [],
  missing_slots: [],
  admission_requests: [],
};

void assistantQuery;
void assistantResult;
