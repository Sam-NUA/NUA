/** Windows Hello could back this via a native IPC call, but no such
 * bridge method exists in apps/windows/src/main.cjs yet — same
 * "not implemented, not faked" story as web. See web/BiometricService.js. */
export * from '../web/BiometricService';
