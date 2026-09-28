import type { DeepLinkReference, MaxTransportState, UpdateReservation } from './transport-state.js';
import { AppError, ERROR_CODES } from './errors.js';
import {
  createLeaseToken,
  hashTransportKey,
  validateDeepLinkReference,
  validateLeaseToken,
  validateNonce,
  validateStateKey,
  validateTtl,
} from './transport-state.js';

type ExpiringCount = { count: number; expiresAt: number };
type UpdateState = { status: 'lease'; token: string; expiresAt: number } | { status: 'done'; expiresAt: number };
type ExpiringReference = { value: DeepLinkReference; expiresAt: number };
const MAX_MEMORY_ENTRIES = 10_000;

export class MemoryMaxTransportState implements MaxTransportState {
  private readonly windows = new Map<string, ExpiringCount>();
  private readonly updates = new Map<string, UpdateState>();
  private readonly deepLinks = new Map<string, ExpiringReference>();
  private operations = 0;

  constructor(private readonly now: () => number = Date.now) {}

  async incrementWindow(key: string, ttlSeconds: number): Promise<number> {
    const checkedKey = hashTransportKey(validateStateKey(key));
    validateTtl(ttlSeconds, 1, 86_400, 'ttlSeconds');
    const now = this.now();
    this.maintain(now);
    const current = this.windows.get(checkedKey);
    if (!current || current.expiresAt <= now) {
      if (!current) this.ensureCapacity(now);
      this.windows.set(checkedKey, { count: 1, expiresAt: now + ttlSeconds * 1000 });
      return 1;
    }
    current.count += 1;
    return current.count;
  }

  async reserveUpdate(key: string, leaseTtlSeconds: number): Promise<UpdateReservation> {
    const checkedKey = hashTransportKey(validateStateKey(key));
    validateTtl(leaseTtlSeconds, 1, 600, 'leaseTtlSeconds');
    const now = this.now();
    this.maintain(now);
    const current = this.updates.get(checkedKey);
    if (!current || current.expiresAt <= now) {
      if (!current) this.ensureCapacity(now);
      const leaseToken = createLeaseToken();
      this.updates.set(checkedKey, { status: 'lease', token: leaseToken, expiresAt: now + leaseTtlSeconds * 1000 });
      return { status: 'reserved', leaseToken };
    }
    return current.status === 'done' ? { status: 'processed' } : { status: 'busy' };
  }

  async completeUpdate(key: string, leaseToken: string, doneTtlSeconds: number): Promise<boolean> {
    const checkedKey = hashTransportKey(validateStateKey(key));
    const checkedToken = validateLeaseToken(leaseToken);
    validateTtl(doneTtlSeconds, 60, 604_800, 'doneTtlSeconds');
    this.maintain(this.now());
    const current = this.updates.get(checkedKey);
    if (!current || current.status !== 'lease' || current.token !== checkedToken || current.expiresAt <= this.now()) return false;
    this.updates.set(checkedKey, { status: 'done', expiresAt: this.now() + doneTtlSeconds * 1000 });
    return true;
  }

  async releaseUpdate(key: string, leaseToken: string): Promise<boolean> {
    const checkedKey = hashTransportKey(validateStateKey(key));
    const checkedToken = validateLeaseToken(leaseToken);
    this.maintain(this.now());
    const current = this.updates.get(checkedKey);
    if (!current || current.status !== 'lease' || current.token !== checkedToken || current.expiresAt <= this.now()) return false;
    return this.updates.delete(checkedKey);
  }

  async storeDeepLink(nonce: string, reference: DeepLinkReference, ttlSeconds: number): Promise<boolean> {
    const checkedNonce = hashTransportKey(validateNonce(nonce));
    const checkedReference = validateDeepLinkReference(reference);
    validateTtl(ttlSeconds, 1, 86_400, 'ttlSeconds');
    const now = this.now();
    this.maintain(now);
    const current = this.deepLinks.get(checkedNonce);
    if (current && current.expiresAt > now) return false;
    if (!current) this.ensureCapacity(now);
    this.deepLinks.set(checkedNonce, { value: checkedReference, expiresAt: now + ttlSeconds * 1000 });
    return true;
  }

  async consumeDeepLink(nonce: string): Promise<DeepLinkReference | undefined> {
    const checkedNonce = hashTransportKey(validateNonce(nonce));
    this.maintain(this.now());
    const current = this.deepLinks.get(checkedNonce);
    if (!current || current.expiresAt <= this.now()) {
      this.deepLinks.delete(checkedNonce);
      return undefined;
    }
    this.deepLinks.delete(checkedNonce);
    return current.value;
  }

  private maintain(now: number): void {
    this.operations += 1;
    if (this.operations % 128 !== 0 && this.entryCount() < MAX_MEMORY_ENTRIES) return;
    for (const [key, entry] of this.windows) if (entry.expiresAt <= now) this.windows.delete(key);
    for (const [key, entry] of this.updates) if (entry.expiresAt <= now) this.updates.delete(key);
    for (const [key, entry] of this.deepLinks) if (entry.expiresAt <= now) this.deepLinks.delete(key);
  }

  private ensureCapacity(now: number): void {
    this.maintain(now);
    if (this.entryCount() >= MAX_MEMORY_ENTRIES) {
      throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'memory_state_capacity' });
    }
  }

  private entryCount(): number {
    return this.windows.size + this.updates.size + this.deepLinks.size;
  }
}
