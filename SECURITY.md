# Security Policy

## Reporting a Vulnerability

If you believe you've found a security issue in this SDK or the OCRQueen
service, please report it privately — **do not open a public issue**.

Email: **security@ocrqueen.com**

Please include:
- A description of the issue
- Steps to reproduce
- The version affected
- Any proof-of-concept code

We aim to acknowledge within **2 business days** and ship a fix within
**30 days** for confirmed high-severity issues. Coordinated disclosure
preferred — please give us a chance to ship the fix before publishing
the details.

## Scope

In scope for this repository:
- The SDK source code itself
- Build / release tooling that affects what users install

Out of scope (report directly via the OCRQueen support channel):
- Vulnerabilities in the OCRQueen service itself
- Vulnerabilities in third-party dependencies (please file with that
  project; we'll bump after their patch lands)

## Supported Versions

Pre-1.0 we only support the **latest** minor release. Once we hit 1.0,
the most recent two minor lines will receive security patches.
