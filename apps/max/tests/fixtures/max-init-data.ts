import { createHmac } from 'node:crypto';

export const TEST_BOT_TOKEN = 'fixture-only-max-bot-token';

type InitDataOptions = Readonly<{
  userId?: number;
  authDate?: number;
  userExtras?: Readonly<Record<string, unknown>>;
}>;

export const createSignedInitData = (options: InitDataOptions = {}): string => {
  const parameters = new URLSearchParams({
    auth_date: String(options.authDate ?? Math.floor(Date.now() / 1000)),
    user: JSON.stringify({ id: options.userId ?? 42, first_name: 'Fixture', username: 'fixture_user', ...options.userExtras }),
  });
  const dataCheckString = [...parameters.entries()]
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n');
  const secret = createHmac('sha256', 'WebAppData').update(TEST_BOT_TOKEN, 'utf8').digest();
  const hash = createHmac('sha256', secret).update(dataCheckString, 'utf8').digest('hex');
  parameters.set('hash', hash);
  return parameters.toString();
};
