(() => {
  const ROOT = "#scrPage";
  const API_PATH = /^\/settings\/api\/?$/;
  const endpoints = [
    {
      path: "/api/status",
      summary: "Current Robinhood Chain block and ETH/USD reference.",
      test: () => "/api/status",
    },
    {
      path: "/api/feed?column=new&limit=5",
      summary: "Recent active ETH-paired Pons curves, priced from direct curve quotes.",
      test: () => "/api/feed?column=new&limit=5",
    },
    {
      path: "/api/search?q=pons&limit=5",
      summary: "Search the recent Pons launch window.",
      test: () => "/api/search?q=pons&limit=5",
    },
    {
      path: "/api/token/{address}/market",
      summary: "Pons token supply, live curve price, and calculated market cap.",
      test: (token) => token ? `/api/token/${encodeURIComponent(token)}/market` : null,
    },
    {
      path: "/api/trade/quote?tok=…&side=buy&wei=…",
      summary: "Read-only quote; use a Privy wallet to sign any transaction.",
      test: (token) => token
        ? `/api/trade/quote?tok=${encodeURIComponent(token)}&side=buy&wei=1000000000000000&slippage=5`
        : null,
    },
    {
      path: "/api/trade/balances?owner=…&tok=…",
      summary: "Live wallet and token balances at the latest Robinhood Chain block.",
      test: (token) => token && window.SentroWallet?.address
        ? `/api/trade/balances?owner=${encodeURIComponent(window.SentroWallet.address)}&tok=${encodeURIComponent(token)}`
        : null,
    },
  ];

  const text = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value == null ? "—" : String(value);
  };
  const formatUsd = (value) => {
    const number = Number(value);
    return Number.isFinite(number) && number > 0
      ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(number)
      : "Unavailable";
  };
  const mount = () => {
    const root = document.querySelector(ROOT);
    if (!root) return;
    if (!API_PATH.test(location.pathname)) {
      window.clearInterval(window.__NORYX_API_LIVE_TIMER);
      window.__NORYX_API_LIVE_STREAM?.close();
      window.__NORYX_API_LIVE_TIMER = null;
      window.__NORYX_API_LIVE_STREAM = null;
      return;
    }
    if (root.querySelector("#api-live-console")) return;
    root.innerHTML = `
      <section class="api-live" id="api-live-console" aria-labelledby="apiLiveTitle">
        <header class="api-live__head">
          <p class="eyebrow">NORYX · LIVE DATA</p>
          <h1 class="api-live__title" id="apiLiveTitle">Robinhood Chain API</h1>
          <p class="api-live__muted">Public read endpoints use Robinhood Chain RPC directly. No Sentro indexer fallback and no fabricated market values.</p>
          <p><a class="api-live__link" href="/v1/openapi.json" target="_blank" rel="noopener">OpenAPI 3.1 specification</a></p>
        </header>
        <section class="api-live__status" aria-label="Live service status">
          <div class="api-live__metric"><small>RPC status</small><b id="apiLiveRpc">Connecting…</b></div>
          <div class="api-live__metric"><small>Latest block</small><b id="apiLiveBlock">—</b></div>
          <div class="api-live__metric"><small>ETH/USD</small><b id="apiLiveEth">—</b></div>
          <div class="api-live__metric"><small>Active curve tokens</small><b id="apiLiveTokens">—</b></div>
          <div class="api-live__metric"><small>Updated</small><b id="apiLiveTime">—</b></div>
        </section>
        <section class="api-live__panel" aria-labelledby="apiLiveEndpoints">
          <h2 id="apiLiveEndpoints">Available endpoints</h2>
          <p class="api-live__muted">Select Test to make a real request and inspect the response from this backend.</p>
          <div class="api-live__grid" id="apiLiveEndpointsList"></div>
          <pre class="api-live__result" id="apiLiveResult" aria-live="polite">Choose an endpoint to test it.</pre>
        </section>
        <section class="api-live__panel" aria-labelledby="apiLiveLimits">
          <h2 id="apiLiveLimits">Live-data limits</h2>
          <p class="api-live__warning">Pons trade history, candles, holder history, authenticated API keys, and paid plans are not enabled yet. Those endpoints are reported unavailable; they are not populated with sample rows.</p>
        </section>
      </section>`;

    const list = document.querySelector("#apiLiveEndpointsList");
    for (const endpoint of endpoints) {
      const card = document.createElement("article");
      card.className = "api-live__endpoint";
      const path = document.createElement("code");
      path.textContent = `GET ${endpoint.path}`;
      const summary = document.createElement("p");
      summary.textContent = endpoint.summary;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.apiTest = endpoint.path;
      button.textContent = "Test endpoint";
      card.append(path, summary, button);
      list.append(card);
    }

    const fetchJson = async (path) => {
      const response = await fetch(path, { headers: { accept: "application/json" } });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || body.error || `HTTP ${response.status}`);
      return body;
    };
    const refresh = async () => {
      if (!API_PATH.test(location.pathname) || !document.querySelector("#api-live-console")) return;
      try {
        const [status, feed] = await Promise.all([
          fetchJson("/api/status"),
          fetchJson("/api/feed?column=new&limit=5"),
        ]);
        if (!API_PATH.test(location.pathname)) return;
        text("#apiLiveRpc", "Connected · Robinhood Chain");
        document.querySelector("#apiLiveRpc")?.classList.add("api-live__ok");
        text("#apiLiveBlock", Number(status.head).toLocaleString("en-US"));
        text("#apiLiveEth", formatUsd(status.eth_usd));
        text("#apiLiveTokens", `${feed.total ?? feed.rows.length}${feed.scan_truncated ? "+" : ""}`);
        text("#apiLiveTime", new Date(status.timestamp * 1000).toLocaleTimeString());
      } catch (error) {
        text("#apiLiveRpc", `Unavailable · ${error.message}`);
        document.querySelector("#apiLiveRpc")?.classList.remove("api-live__ok");
      }
    };
    list.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-api-test]");
      if (!button) return;
      const endpoint = endpoints.find((item) => item.path === button.dataset.apiTest);
      const needsToken = endpoint && (endpoint.path.includes("{address}") || endpoint.path.includes("tok="));
      const feed = needsToken ? await fetchJson("/api/feed?column=new&limit=1").catch(() => null) : null;
      const token = feed?.rows?.[0]?.token;
      const path = endpoint?.test(token);
      const result = document.querySelector("#apiLiveResult");
      if (!path) {
        result.textContent = "No live ETH-paired Pons token is available to test this endpoint.";
        return;
      }
      result.textContent = "Requesting…";
      try {
        const body = await fetchJson(path);
        result.textContent = JSON.stringify(body, null, 2);
      } catch (error) {
        result.textContent = error.message;
      }
    });
    window.clearInterval(window.__NORYX_API_LIVE_TIMER);
    window.__NORYX_API_LIVE_STREAM?.close();
    const stream = new EventSource("/api/feed/stream");
    window.__NORYX_API_LIVE_STREAM = stream;
    stream.addEventListener("hello", (event) => {
      const data = JSON.parse(event.data);
      text("#apiLiveRpc", "Connected · Robinhood Chain");
      document.querySelector("#apiLiveRpc")?.classList.add("api-live__ok");
      text("#apiLiveBlock", Number(data.head).toLocaleString("en-US"));
      if (data.eth_usd) text("#apiLiveEth", formatUsd(data.eth_usd));
    });
    stream.addEventListener("tick", (event) => {
      const data = JSON.parse(event.data);
      text("#apiLiveBlock", Number(data.head).toLocaleString("en-US"));
      if (data.eth_usd) text("#apiLiveEth", formatUsd(data.eth_usd));
      text("#apiLiveTime", new Date(data.timestamp * 1000).toLocaleTimeString());
    });
    stream.addEventListener("launch", refresh);
    stream.onerror = () => {
      text("#apiLiveRpc", "Reconnecting to Robinhood Chain…");
      document.querySelector("#apiLiveRpc")?.classList.remove("api-live__ok");
    };
    refresh();
    window.__NORYX_API_LIVE_TIMER = window.setInterval(refresh, 15000);
  };

  const observer = new MutationObserver(mount);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("popstate", mount);
  mount();
})();
