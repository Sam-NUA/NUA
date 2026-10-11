# Owner and client access

Each person signs in with the email saved on their account. There is no shared
owner username or default PIN. A new browser starts with email sign-in; a staff
terminal remembers its last successful method.

## Everyday use

- Forgotten password: choose **Email → Forgot password**. Use the latest email
  link within 30 minutes. It works once. Check spam or contact your venue's setup
  administrator if it does not arrive.
- Change a known password: **Settings → Security → Your account access**. Enter
  the current password and the new password twice. Sign in again afterward.
- PIN: the owner sets each person's PIN in **Settings → Staff**. Creating or
  changing an email password does not create a PIN.
- PIN access requires an active business membership. Accounts requiring two-factor
  authentication must use email sign-in and their authenticator; PIN-only manager
  approval is also unavailable for those accounts.
- Two-factor authentication: keep the recovery codes offered in Security.
  Password recovery does not remove two-factor authentication.

## Before handing a venue to a new owner/client

Provision the correct venue and personal account through the authenticated
administration workflow. Do not reuse one owner's credentials across clients.
Confirm the account belongs to the correct business before handing it over.
This change does not enable public signup into an existing venue or implement
ownership transfer between businesses.

Configure these server-only variables once per deployment:

| Variable | Purpose |
| --- | --- |
| `FRONTEND_URL` | Canonical HTTPS app origin, with no path/query. Production NUA POS uses `https://app.nuapos.com.au`. |
| `SENDGRID_API_KEY` | Secret for the configured email provider. |
| `SENDGRID_FROM_EMAIL` | Sender verified with that provider. |
| `OWNER_RECOVERY_KEY` | Optional emergency operator secret, separate from account passwords. |

Redeploy after changing environment settings. `/api/auth/access-options` reports
configuration readiness, not confirmed email delivery. Verify an actual reset
email arrives in the owner's inbox before handover. Test the link, new-password
sign-in, PIN, and any enabled second factor on the intended terminal.

Missing email configuration produces a clear unavailable state for all email
addresses. Provider failures are logged without reset links and do not reveal
whether an email has an account. Failed delivery invalidates that reset link.

## Existing locked owner

Prefer email recovery once delivery is configured. If email is unavailable, the
operator can configure `OWNER_RECOVERY_KEY`, redeploy, and open `/owner-recovery`.
The owner enters the key, their existing account email, and a new password.
Remove the emergency key and redeploy after recovery when it is no longer needed.
Do not send passwords, PINs, recovery keys, or reset links through support chat.

`ADMIN_EMAIL` and `ADMIN_PASSWORD` are bootstrap settings. They create an account
when absent; they never reset the saved password of an existing account. Changing
the email can create a separate account, so these variables are not an ownership
transfer mechanism. Saved credentials survive cold starts and redeploys.

Reset links are random, stored only as hashes, expire after 30 minutes, and are
claimed atomically. A newer request replaces an older link. Password changes
invalidate earlier access/refresh tokens and outstanding sign-in challenges;
email reset and in-app change also clear trusted-device records. Users retain
their roles, business membership and second-factor configuration.


### Owner PIN and multiple owners

The operator recovery screen accepts an optional four-digit PIN and confirmation.
Leave both blank to preserve the current PIN. Recovery selects the requested owner
email, including when several owners exist; it cannot create a different owner
when an owner already exists. Tokens are bound to the account and its current
password, expire after 15 minutes, and work once. Start recovery again if a PIN
is already assigned. Ambiguous legacy PIN assignments are denied at sign-in.

`ADMIN_PIN` is an optional first-insert bootstrap value only. Changing it, or
`ADMIN_PASSWORD`, does not overwrite an existing account. Existing owners use
recovery or authenticated account settings. Never commit production credentials.

Release setup: configure the canonical `FRONTEND_URL`, verified SendGrid sender
and `SENDGRID_API_KEY` for email resets. For operator recovery, configure
`OWNER_RECOVERY_KEY` as a secret and redeploy. The owner enters the new password
and PIN privately, then verifies email and PIN sign-in. Remove the operator key
when it is no longer required. Test delivery and recovery before handing over.
