---
title: Privacy
---

# Privacy

Noryx stores the connected public wallet address and local preferences in the
browser when those features are used. Privy handles email OTP authentication
and embedded-wallet session data. A public blockchain address is not a secret.

RPC and market-data providers may receive normal network metadata required to
answer requests. Noryx never requests or stores seed phrases or private keys.
If you explicitly export a private key, Privy's isolated export modal handles
that action.

Local browser data can be removed by disconnecting the wallet or clearing site
storage. Production deployments should configure their own provider policies
and retention controls.
