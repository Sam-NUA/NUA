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
