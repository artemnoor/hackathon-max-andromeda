import type { components } from '../../andromeda/generated/public-api.js';
import {
  callbackActionDefinitions,
  type CallbackAction,
  type CallbackActionDefinition,
} from '../callbacks/actions.js';

type ResponseAction = components['schemas']['ResponseAction'];
type ResponseActionItem = components['schemas']['ResponseActionItem'];

type ReadOnlyResponseAction = Readonly<{
  fallbackLabel: string;
  prompt: string;
}>;

const READ_ONLY_ACTIONS: Partial<Record<ResponseAction, ReadOnlyResponseAction>> = Object.freeze({
  show_details: Object.freeze({
    fallbackLabel: 'Подробнее',
    prompt: 'Расскажи подробнее об этом результате',
  }),
  compare: Object.freeze({
    fallbackLabel: 'Сравнить программы',
    prompt: 'Сравни первые две программы из подборки',
  }),
  change_scope: Object.freeze({
    fallbackLabel: 'Изменить параметры',
    prompt: 'Измени параметры этого запроса',
  }),
  show_curriculum: Object.freeze({
    fallbackLabel: 'Учебный план',
    prompt: 'Покажи учебный план выбранной программы',
  }),
});

const supportedActionNames = Object.keys(READ_ONLY_ACTIONS) as ResponseAction[];

export const responseActionCallbackDefinitions: readonly CallbackActionDefinition[] =
  callbackActionDefinitions(supportedActionNames.map((action) => Object.freeze({
    namespace: 'assistant',
    verb: action,
    requiresResource: false,
  })));

export const responseActionButton = (
  item: ResponseActionItem,
  safeLabel: (value: string) => string | undefined,
): Readonly<{ text: string; callbackPayload: string }> | undefined => {
  const definition = Object.hasOwn(READ_ONLY_ACTIONS, item.action)
    ? READ_ONLY_ACTIONS[item.action]
    : undefined;
  if (!definition) return undefined;
  const text = safeLabel(item.label) ?? definition.fallbackLabel;
  return Object.freeze({
    text,
    callbackPayload: `assistant:${item.action}`,
  });
};

export const promptForResponseAction = (action: CallbackAction): string | undefined => {
  if (action.namespace !== 'assistant') return undefined;
  const responseAction = action.verb as ResponseAction;
  return Object.hasOwn(READ_ONLY_ACTIONS, responseAction)
    ? READ_ONLY_ACTIONS[responseAction]?.prompt
    : undefined;
};
