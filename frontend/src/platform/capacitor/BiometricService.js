/** No biometric plugin (e.g. `@capacitor-community/biometric-auth`) is
 * installed — same "not implemented, not faked" story as web. Android's
 * BiometricPrompt / iOS's Face ID/Touch ID are both real, well-supported
 * targets for this interface once a plugin is chosen; tracked in
 * MOBILE_DESKTOP_BACKLOG.md as genuinely not done. See
 * web/BiometricService.js. */
export * from '../web/BiometricService';
