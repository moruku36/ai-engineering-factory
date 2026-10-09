import {createMockBroker} from "./broker-mock.mjs";

export function runContractChecks(factory = createMockBroker) {
  let passed = 0;
  const context = {caller: "mock-launcher", task: "mock-task"};
  const check = (condition, label) => {
    if (!condition) throw new Error(label);
    passed++;
  };
  const broker = factory();
  const ref = broker.issueForTrustedTestHarness(100);
  const req = {handle: ref, operation: "service.status"};
  check(broker.execute(req, context, 100).status === "mock-completed", "allowed");
  check(broker.execute(req, context, 100).status === "denied", "replay");
  const expire = broker.issueForTrustedTestHarness(100);
  check(broker.execute({...req, handle: expire}, context, 130).status === "denied", "expired");
  const revoke = broker.issueForTrustedTestHarness(100);
  broker.revokeForTrustedTestHarness(revoke);
  check(broker.execute({...req, handle: revoke}, context, 101).status === "denied", "revoked");
  const ref2 = broker.issueForTrustedTestHarness(100);
  const req2 = {...req, handle: ref2};
  check(broker.execute(req2, {...context, caller: "other"}, 101).status === "denied", "identity");
  check(broker.execute(req2, {...context, task: "other"}, 101).status === "denied", "task");
  check(broker.execute({...req2, operation: "pod.start"}, context, 101).status === "denied", "billable");
  check(broker.execute({...req2, operation: "secret.read"}, context, 101).status === "denied", "read");
  check(broker.execute({...req2, url: "https://example.invalid"}, context, 101).status === "denied", "URL");
  check(broker.execute({...req2, argv: ["echo"]}, context, 101).status === "denied", "argv");
  check(broker.execute({...req2, handle: "unknown"}, context, 101).status === "denied", "unknown");
  check(broker.execute(req2, context, NaN).status === "denied", "clock");
  check(broker.execute(null, context, 101).status === "denied", "null");
  check(broker.execute(req2, context, 101).status === "mock-completed", "denial preserves grant");
  const keys = Object.keys(broker.execute(req2, context, 101));
  check(keys.join(",") === "status", "output whitelist");
  check(!("read" in broker) && !("launch" in broker), "no secret or launcher API");
  return passed;
}
const passed = runContractChecks();
if (passed !== 16) throw new Error("unexpected count");
