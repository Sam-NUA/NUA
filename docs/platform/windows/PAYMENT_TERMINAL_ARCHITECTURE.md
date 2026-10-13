# Payment terminals

No terminal payment adapter is implemented or certified by this Windows foundation. Existing recorded `card` transactions must not be confused with gateway authorization. The new queue accepts simple cash only. No PAN/CVV, terminal shared secret or custom offline card authorization belongs in local state.

Future terminal flow: backend-authorized intent → provider operation ID → terminal SDK → confirmed/declined/unknown → server verification → idempotent sale finalization. Timeout is unknown; query provider status with the same operation ID before any retry. App restart must recover unknown operations without duplicate charge. Refund/void pairing requires the same tenant and role checks. Test in provider sandbox and on physical supported terminal before enabling the capability.
