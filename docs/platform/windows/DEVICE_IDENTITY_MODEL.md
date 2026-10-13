# Device identity and revocation

Separate install identifier, business terminal assignment, authenticated user and trusted MFA device. An install UUID is not a credential. Existing licensing `/device/activate` and `/device/revoke` scope license inventory and require privileged users; they do not cryptographically authenticate every POS request.

Next server package: owner/manager approves pairing; server issues revocable credential bound to business/location/device; OS secure store holds it; requests carry device context plus staff authentication; server checks both current revocation and business membership. Rotation and revocation must stop new requests and replay. Offline authorization lease and maximum offline duration require an explicit policy. PIN alone cannot select arbitrary business or bypass MFA. No fabricated registration endpoint/token has been added here.
