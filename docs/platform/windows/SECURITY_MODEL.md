# Platform security

Native client is untrusted. Server owns price, permissions, tenant membership, loyalty and payment state. No backend security check was weakened and seed credentials remain create-once. No credentials were added to this package.

Windows isolates renderer and host, uses a trusted bundled origin and sender-checked narrow IPC. No generic execute/file/network bridge exists. CSP blocks arbitrary scripts; permissions default deny. In-memory Chromium session prevents persistent browser credentials, but shared AuthContext still exposes access tokens to its renderer at runtime. OS-encrypted persistence exists as an unexposed primitive; shared auth migration is not complete. DPAPI protects other Windows users, not malware running as the same user.

Queue scope/account fences and atomic encrypted files are defense in depth, not backend authorization. Transport must verify the current server identity and pin the matching credential. No local PIN can create trust. Legacy queue/cache account isolation is a release blocker. Never log credentials, full financial/customer payloads or unrestricted exceptions; queue error records contain only status class. Foundation host does not upload telemetry.

Signing, update verification, minimum-client compatibility and revocation enforcement remain release gates. No production deployment, Vercel config/env change (other than this branch's Git-deploy exclusion), Railway action or live financial test is performed.
