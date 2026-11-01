(() => {
  const appId = window.PRIVY_APP_ID;
  const chain = {
    id: 4663,
    name: "Robinhood Chain",
    network: "robinhood",
    nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
    rpcUrls: {
      default: { http: ["https://robinhood-rpc.publicnode.com"] },
      public: { http: ["https://robinhood-rpc.publicnode.com"] },
    },
    blockExplorers: {
      default: { name: "Robinhood Explorer", url: "https://robinhoodchain.blockscout.com" },
    },
  };
  let latestAdapter = null;
  const publish = (adapter) => {
    latestAdapter = adapter;
    window.SentroPrivy = adapter;
    window.dispatchEvent(new CustomEvent("sentro-privy", { detail: adapter }));
  };
  const reportFailure = (error) => {
    const message = error?.message || "Privy authentication could not initialize.";
    console.error("Noryx Privy initialization failed", error);
    publish({
      ready: true,
      authenticated: false,
      address: null,
      label: "Email",
      login: async () => { throw new Error(message); },
      logout: async () => {},
      provider: async () => { throw new Error(message); },
      switchChain: async () => { throw new Error(message); },
      token: async () => null,
    });
  };

  const start = async () => {
    if (!appId) throw new Error("Privy app ID is missing. Configure NORYX_PRIVY_APP_ID.");
    const [React, ReactDOM, Privy] = await Promise.all([
      import("react"),
      import("react-dom/client"),
      import("https://esm.sh/@privy-io/react-auth@3.51.0?external=react,react-dom"),
    ]);
    const { PrivyProvider, usePrivy, useWallets, useExportWallet } = Privy;
    const host = document.createElement("div");
    host.id = "noryx-privy-host";
    host.hidden = true;
    document.body.append(host);

    function PrivyBridge() {
      const session = usePrivy();
      const walletState = useWallets();
      const { exportWallet } = useExportWallet();

      React.useEffect(() => {
        let cancelled = false;
        const sync = async () => {
          const wallets = walletState.wallets || [];
          const embeddedWallet = wallets.find((wallet) => wallet.walletClientType === "privy");
          const selectedWallet = embeddedWallet || wallets[0];
          let ethereumProvider = null;
          if (selectedWallet?.getEthereumProvider) {
            ethereumProvider = await selectedWallet.getEthereumProvider();
          }
          if (cancelled) return;
          const userWallet = session.user?.linkedAccounts?.find(
            (account) => account.type === "wallet" && account.chainType === "ethereum",
          );
          const address = selectedWallet?.address || userWallet?.address || null;
          const adapter = {
            ready: !!session.ready,
            authenticated: !!session.authenticated,
            address: address ? address.toLowerCase() : null,
            label: session.user?.email?.address || "Email",
            login: () => session.login(),
            logout: () => session.logout(),
            provider: async () => {
              if (!ethereumProvider) throw new Error("No Privy embedded Ethereum wallet is available.");
              return ethereumProvider;
            },
            switchChain: async (chainId) => {
              if (!ethereumProvider) throw new Error("No Privy embedded Ethereum wallet is available.");
              const targetId = Number(chainId);
              try {
                await ethereumProvider.request({
                  method: "wallet_switchEthereumChain",
                  params: [{ chainId: `0x${targetId.toString(16)}` }],
                });
              } catch (error) {
                if (error?.code !== 4902) throw error;
                await ethereumProvider.request({
                  method: "wallet_addEthereumChain",
                  params: [{
                    chainId: `0x${targetId.toString(16)}`,
                    chainName: chain.name,
                    nativeCurrency: chain.nativeCurrency,
                    rpcUrls: chain.rpcUrls.default.http,
                    blockExplorerUrls: [chain.blockExplorers.default.url],
                  }],
                });
              }
            },
            token: () => session.getAccessToken(),
            exportKey: async () => {
              if (!session.authenticated) throw new Error("Sign in to export your wallet key.");
              if (!embeddedWallet?.address) {
                throw new Error("Your Privy embedded wallet is not ready yet. Refresh your profile and try again.");
              }
              await exportWallet({ address: embeddedWallet.address });
            },
          };
          publish(adapter);
        };
        sync().catch(reportFailure);
        return () => { cancelled = true; };
      }, [session.ready, session.authenticated, session.user, walletState.wallets, exportWallet]);

      return null;
    }

    ReactDOM.createRoot(host).render(
      React.createElement(
        PrivyProvider,
        {
          appId,
          config: {
            loginMethods: ["email"],
            defaultChain: chain,
            supportedChains: [chain],
            appearance: {
              theme: "dark",
              accentColor: "#b8df15",
              logo: `${window.location.origin}/images/noryx-favicon.png`,
            },
            embeddedWallets: {
              ethereum: { createOnLogin: "users-without-wallets" },
            },
          },
        },
        React.createElement(PrivyBridge),
      ),
    );
  };

  start().catch(reportFailure);
})();
