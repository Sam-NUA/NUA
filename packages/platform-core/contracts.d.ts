/** Server-verified identity; local values never confer backend permission. */
export interface VerifiedIdentity { businessId: string; userId: string; deviceId: string }
export type Availability = 'available' | 'permission-required' | 'unsupported' | 'unverified';
export interface Capability { status: Availability; reason?: string }
export interface PrinterAdapter {
  listPrinters(): Promise<Array<{name: string; displayName: string; isDefault: boolean}>>;
  printReceipt(receipt: Receipt): Promise<{status: 'submitted' | 'cancelled-or-failed'}>;
}
export interface Receipt {
  businessName: string; receiptId: string; totalCents: number; footer?: string;
  items: Array<{name: string; quantity: number; totalCents: number}>;
}
/** Implementations must reject unavailable operations, never fabricate success. */
export interface PlatformCapabilities {
  printer: Capability; scanner: Capability; cashDrawer: Capability;
  paymentTerminal: Capability; camera: Capability; network: Capability;
  notifications: Capability; biometrics: Capability; updates: Capability;
  deviceIdentity: Capability; secureStorage: Capability;
}
export interface AtomicScopedStore {
  read(scope: string): Promise<unknown | null>;
  write(scope: string, value: unknown): Promise<void>;
}
