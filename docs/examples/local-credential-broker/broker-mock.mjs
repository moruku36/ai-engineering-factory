// Offline contract mock. No credentials, OS calls, network, shell, or persistence.
// Trusted methods below must never be exposed as worker/model tools.
export function createMockBroker() {
  const grants = new Map();
  let sequence = 0;
  const deny = () => Object.freeze({status: "denied"});
  const operation = "service.status";
  const caller = "mock-launcher";
  const task = "mock-task";
  function issueForTrustedTestHarness(now, ttl = 30) {
    if (!Number.isSafeInteger(now) || !Number.isSafeInteger(ttl) || ttl <= 0 || ttl > 60) {
      throw new Error("invalid mock grant");
    }
    const handle = "mock-ref-" + (++sequence);
    grants.set(handle, {expires: now + ttl, consumed: false, revoked: false});
    return handle; // Predictable TEST handle, never a production capability.
  }
  function revokeForTrustedTestHarness(handle) {
    const grant = grants.get(handle);
    if (grant) grant.revoked = true;
  }
  function execute(request, trustedContext, now) {
    // Context is simulated here; production must obtain it from authenticated transport.
    if (!request || typeof request !== "object" || Array.isArray(request) ||
        Object.keys(request).sort().join(",") !== "handle,operation" ||
        !trustedContext || trustedContext.caller !== caller || trustedContext.task !== task ||
        request.operation !== operation || !Number.isSafeInteger(now)) return deny();
    const grant = grants.get(request.handle);
    if (!grant || grant.revoked || grant.consumed || now >= grant.expires) return deny();
    // Consume BEFORE the mock side effect. There is no retry/reset path.
    grant.consumed = true;
    return Object.freeze({status: "mock-completed"});
  }
  return Object.freeze({issueForTrustedTestHarness, revokeForTrustedTestHarness, execute});
}
