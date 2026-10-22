# Live trading release gates

The private dashboard remains mock-only. The CLI still requires explicit `--enable-live-trading`
and credentials for a live adapter. That flag is not certification of broker compatibility.
Do not connect a funded live account based on the mock test results.

Implemented foundations:

- Global capital cap, cash checks serialized across submissions, and finite numeric validation.
- Quote age, depth, spread, daily market-price bands, and limit-order price-band checks.
- A broker-supplied previous close is required; missing market timestamps are not replaced with
  local receipt time in the live adapters. Those normalized field mappings remain unverified.
- A final halt check after asynchronous balance reads and before submitting an order.
- No automatic retry of submissions, and durable pending markers for ambiguous outcomes.
- Known-order cancellation with terminal-status verification, bounded timeout, and saved snapshots.
- Validation of order identity, submitted quantity/price/type, fills, and fees.
- Realized cycle accounting uses reported broker fees. Estimated fees still inform entry sizing
  and the target sell price and must be validated against the real fee schedule.
- Local database ownership lock, preserved unresolved state, read-only reports, consistent backups,
  and automated mock/failure tests.

Required before any funded release:

1. Obtain official broker API documentation and a sandbox account. Verify authentication/signatures,
   token expiry/refresh, approved endpoints, supported instruments, exchange timestamps/timezone,
   previous close source, tick sizes, lot sizes, trading sessions/holidays, rate limits, and fee schedules.
   The current adapters assume normalized fields and status enums; they are not verified integrations.
2. Add contract tests and sandbox integration tests for order acceptance, rejects, partial fills,
   expiration, cancel/fill races, unknown statuses, timeouts, rate limits, and network interruptions.
   Run complete buy/sell/recovery cycles with the broker's real schemas and fee rules.
3. Implement broker-supported client order IDs/idempotency and order discovery. Reconcile open orders,
   fills, holdings, and available cash on startup and after ambiguous submissions. Provide an audited,
   explicit operator recovery workflow. The current read-only report does not perform reconciliation.
4. Define and enforce portfolio exposure, daily realized/unrealized loss, drawdown, and position limits.
   Implement and test an agreed stop-loss/exit policy. The existing stop-loss calculator does not place
   protective orders. A kill switch cancels known pending orders; it does not liquidate holdings.
5. Validate market data freshness using authoritative exchange timestamps. Daily price-band enforcement
   needs a verified prior close and does not establish market-hours compliance or eliminate price risk.
   If a sell target is outside the allowed band, the engine blocks with holdings retained for review.
6. Add durable audit events and alerts for kill switches, worker failures, unresolved submissions,
   order age, cancellation failures, stale data, reconciliation differences, and loss thresholds.
   A web health check is not a trading health signal. Exercise the incident response runbook.
7. Use a broker-approved secret manager, least-privilege account, credential rotation, and restricted
   network access. CardinalStone authentication currently has no refresh flow. Verify safe error logging.
   Use stronger identity controls and operator roles if multiple users will control live trading.
8. Run exactly one engine per broker account with persistent local storage. The lock protects one
   database, not multiple database paths, hosts, or accounts. Do not share SQLite over a network filesystem.
   Test crashes, database faults, backups/restores, upgrades, rollback, and broker-side orders surviving host loss.
9. Review monetary precision/rounding and use broker-approved tick and fee arithmetic; the prototype
   still uses floats. Pin and audit release dependencies/images and use a reviewed release process.
10. Complete a sustained sandbox soak test and operational/security review, then obtain explicit approval
    for a small, tightly limited funded pilot. No real orders are part of this branch's validation.
