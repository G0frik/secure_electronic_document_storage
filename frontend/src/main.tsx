import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "@/App";
import { AuthProvider } from "@/state/auth";
import { ToastProvider } from "@/state/toast";
import ToastHost from "@/components/ToastHost";

// Self-hosted variable + static weights for the Paper Archive aesthetic.
// IBM Plex Sans (variable) — UI body. IBM Plex Mono — filenames, IDs,
// tokens, the "this is a system" reinforcement.
import "@fontsource-variable/ibm-plex-sans";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import "@/index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <App />
          <ToastHost />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
