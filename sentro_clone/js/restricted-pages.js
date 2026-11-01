(() => {
  const original = window.SentroPages;
  if (!original) return;

  window.SentroPages = (C) => {
    const pages = original(C);
    if (!pages || typeof pages.render !== "function") return pages;

    const restricted = new Set(["ask", "apikeys"]);
    let unsubscribed = null;

    const syncNavigation = () => {
      const signedIn = !!C.W.address;
      document.querySelectorAll(
        '[data-nav="ask"], [data-nav="apikeys"]'
      ).forEach((link) => {
        link.hidden = !signedIn;
      });
      document.querySelectorAll(
        '.status__a[href="/settings/api"], #bnSheet a[href="/settings/api"]'
      ).forEach((link) => {
        link.hidden = !signedIn;
      });
    };

    const renderGuard = (name, el) => {
      if (unsubscribed) {
        unsubscribed();
        unsubscribed = null;
      }

      const loading = C.W.state.status === "init" || C.W.state.status === "loading";
      const configured = C.W.configured();
      el.className = "scr pg";
      document.title = name === "ask" ? "Sign in · Ask AI" : "Sign in · API";
      el.innerHTML = `<h1 class="sr">${name === "ask" ? "Ask AI" : "API"}</h1>
        <div class="pg__b pg__b--gate">
          <div class="empty empty--big gate" data-testid="signin-card" data-gate="${name}">
            <span class="empty__ico">${C.ic(name === "ask" ? "sparkle" : "key", "ico--3")}</span>
            <span class="eyebrow">${name === "ask" ? "Ask AI" : "Noryx API"}</span>
            <h2>${name === "ask" ? "Sign in to ask AI" : "Sign in to manage API keys"}</h2>
            <p>${name === "ask"
              ? "Ask AI answers are available only to signed-in Noryx accounts."
              : "API keys and usage data are available only to signed-in Noryx accounts."}</p>
            <div class="empty__a">
              <button type="button" class="btn btn--buy" data-restricted-signin data-testid="gate-signin"${loading || !configured ? " disabled" : ""}>
                ${loading ? C.ic("loading", "ico--spin") : C.ic("user")}Sign in
              </button>
            </div>
          </div>
        </div>`;

      el.onclick = (event) => {
        if (event.target.closest("[data-restricted-signin]")) C.connect();
      };

      unsubscribed = C.W.onChange((state) => {
        syncNavigation();
        if (state.address && location.pathname === (name === "ask" ? "/ask" : "/settings/api")) {
          pages.render(name, el);
        } else if (!state.address) {
          renderGuard(name, el);
        }
      });
    };

    syncNavigation();
    unsubscribed = C.W.onChange(syncNavigation);

    return {
      ...pages,
      render(name, el, opts) {
        syncNavigation();
        if (restricted.has(name) && !C.W.address) {
          renderGuard(name, el);
          return;
        }
        pages.render(name, el, opts);
      },
    };
  };
})();
