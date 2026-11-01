---
title: Security guide
---

# Security guide

## Wallet safety

Noryx never asks you to enter a seed phrase or private key. Email sign-in and
embedded-wallet key export are handled by Privy. When you choose to export a
key, Privy's isolated export modal displays it; Noryx does not read or store it.
Transactions must be reviewed before signing.

## Verify addresses

Always verify the chain, token contract, recipient, amount, and network fee in
your wallet before signing. Token names and symbols are not unique.

## Read-only services

Market data is fetched from configured public RPC and indexer services. If a
service is unavailable, Noryx reports the error instead of inventing market
data.

## Reporting an issue

Stop signing transactions and record the page URL, contract address, and
wallet provider when reporting a security issue. Do not include private keys or
seed phrases.
