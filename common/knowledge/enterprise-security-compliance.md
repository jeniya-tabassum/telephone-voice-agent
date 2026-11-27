---
title: Deepgram Enterprise — Security, Compliance, SLA, and Bug Bounty
sources:
  - https://deepgram.com/security
  - https://developers.deepgram.com/docs/getting-help
status: current
valid_as_of: 2026-06
---

# Deepgram Enterprise Security and Compliance

## Security and Bug Bounty

Deepgram takes security seriously. To report a security vulnerability or potential bug, contact Deepgram through the official security disclosure process at security@deepgram.com. Deepgram participates in responsible disclosure and coordinates fixes with security researchers.

For security-related issues, contact: security@deepgram.com

## Uptime SLA and Availability

Deepgram offers enterprise-grade uptime SLAs (Service Level Agreements) for paid plans. The standard Deepgram SLA for enterprise customers includes:

- **99.9% uptime guarantee** for paid API access
- Real-time status monitoring at status.deepgram.com
- Incident response SLAs for enterprise customers
- Availability metrics tracked across all APIs: STT, TTS, Voice Agent

For exact SLA terms and availability guarantees, contact Deepgram sales or see deepgram.com/pricing for enterprise plan details.

## Disaster Recovery

Deepgram operates redundant infrastructure across multiple availability zones. The Deepgram API (api.deepgram.com) has disaster recovery capabilities built in, including:

- Multi-region redundancy
- Automatic failover
- Data replication
- Backup and restore procedures for console data

For enterprise disaster recovery documentation, contact sales@deepgram.com.

## Proof of Concept (POC)

Yes, Deepgram supports proof-of-concept (POC) trials. Options:

- **Free tier**: $200 in free API credits — no credit card required, sign up at console.deepgram.com
- **Enterprise POC**: Contact Deepgram sales for a guided POC with dedicated support
- **API Playground**: Try models in-browser at console.deepgram.com/playground without writing code

## Data Encryption

All data transmitted to and from the Deepgram API is encrypted in transit using TLS 1.2+. Deepgram does not store audio data by default — transcription results are returned in the API response. Deepgram is SOC 2 Type II certified and HIPAA compliant (with BAA for healthcare customers).
