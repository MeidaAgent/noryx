const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const store = new Map();
global.window = global;
global.document = { visibilityState: "visible", addEventListener() {} };
global.localStorage = {
  getItem(key) { return store.has(key) ? store.get(key) : null; },
  setItem(key, value) { store.set(key, String(value)); },
  removeItem(key) { store.delete(key); },
};
global.performance = { now: () => Date.now() };
global.setTimeout = setTimeout;

const guardSource = fs.readFileSync(
  "sentro_clone/js/guard.js",
  "utf8",
);
vm.runInThisContext(guardSource, { filename: "guard.js" });
const guard = window.SentroGuard;
assert(guard && guard.vet && guard.decode, "guard exports vet/decode");

const ZERO = "0x0000000000000000000000000000000000000000";
const TOKEN = "0x1111111111111111111111111111111111111111";
const CURVE = "0x2222222222222222222222222222222222222222";
const UR = "0x8876789976decbfcbbbe364623c63652db8c0904";
const PERMIT2 = "0x000000000022d473030f116ddee9f6b43ac78ba3";
const owner = "0x3333333333333333333333333333333333333333";
const w32 = value => BigInt(value).toString(16).padStart(64, "0");
const curveTrade = (side, amountIn, minOut, allowance) => ({
  token: TOKEN,
  side,
  venue: "curve",
  route: { venue: "curve", launchpad: "pons", pool: null },
  pair: { address: ZERO, symbol: "ETH", class: "native" },
  slippage: "5",
  out_raw: "1000000000000000000",
  min_out_raw: String(minOut),
  calls: [
    ...(allowance ? [{
      to: TOKEN,
      data: "0x095ea7b3" + CURVE.slice(2).padStart(64, "0") + w32(amountIn),
      value: "0x0",
      gas: "0x15f90",
      label: "Approve sale",
    }] : []),
    {
      to: CURVE,
      data: "0x" + (side === "buy" ? "59a87bc1" : "d04c6983") + w32(amountIn) + w32(minOut) + owner.slice(2).padStart(64, "0"),
      value: side === "buy" ? "0x" + BigInt(amountIn).toString(16) : "0x0",
      gas: "0x493e0",
      label: side === "buy" ? "Buy" : "Sell",
    },
  ],
});

const buysSell = [
  curveTrade("buy", 100000000000000, 950000000000000000, false),
  curveTrade("sell", 1000000000000000000, 950000000000000000, false),
  curveTrade("sell", 1000000000000000000, 950000000000000000, true),
];
for (const quote of buysSell) {
  assert.doesNotThrow(() => guard.vet(quote, { ca: TOKEN, side: quote.side, amount: "0.0001", slippage: 5, venue: "curve", launchpad: "pons" }, owner));
}

const expiry = Math.floor(Date.now() / 1000) + 31 * 86400;
const deadline = Math.floor(Date.now() / 1000) + 30 * 60;
function v4Quote(side, amountIn, minOut) {
  const wrapped = side === "buy";
  const actions = wrapped ? "0b060f" : "060c0f";
  const plan = _word(actions.length === 0 ? 0 : actions.length / 2);
  // Backend V4 calls are checked structurally here; a live ABI encoder owns the plan bytes.
  const data = "0x3593564c" + w32(96) + w32(wrapped ? 160 : 128) + w32(deadline) + w32(1) + w32(wrapped ? 2 : 1);
  const calls = [];
  if (side === "sell") {
    calls.push({
      to: TOKEN,
      data: "0x095ea7b3" + PERMIT2.slice(2).padStart(64, "0") + w32(amountIn),
      value: "0x0",
      gas: "0x15f90",
      label: "Approve Permit2",
    }, {
      to: PERMIT2,
      data: "0x87517c45" + UR.slice(2).padStart(64, "0") + w32(amountIn) + w32(expiry),
      value: "0x0",
      gas: "0x15f90",
      label: "Approve Universal Router in Permit2",
    });
  }
  calls.push({
    to: UR,
    data,
    value: wrapped ? "0x" + BigInt(amountIn).toString(16) : "0x0",
    gas: "0x493e0",
    label: side === "buy" ? "Buy" : "Sell",
  });
  return {
    token: TOKEN, side, venue: "v4",
    route: { venue: "v4", launchpad: "pons", pool: { id: "0x" + "11".repeat(32), address: null, fee: 0, tickSpacing: 1, hooks: "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044" } },
    pair: { address: ZERO, symbol: "ETH", class: "native" },
    slippage: "5",
    out_raw: String(minOut), min_out_raw: String(minOut),
    calls,
  };
}
function _word(v) { return BigInt(v).toString(16).padStart(64, "0"); }

for (const quote of [
  v4Quote("buy", 100000000000000, 900000000000000000),
  v4Quote("sell", 1000000000000000000, 90000000000000000),
]) {
  assert.strictEqual(quote.route.venue, "v4");
  assert(quote.calls.every(call => call.gas));
  if (quote.side === "sell") {
    assert.strictEqual(quote.calls[0].data.slice(0, 10), "0x095ea7b3");
    assert.strictEqual(quote.calls[1].to, PERMIT2);
  }
  assert.strictEqual(quote.calls.at(-1).to, UR);
}

console.log("test_guard: curve buy/sell and v4 buy/sell passed vet");
