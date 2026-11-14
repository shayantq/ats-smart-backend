import React from "react";
import ReactDOM from "react-dom/client";
import { Provider } from "react-redux";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { store } from "./store/store";
import { queryClient } from "./services/queryClient";
import "./index.css";
import { startThemeSync } from "./store/themeSync";
const stopThemeSync = startThemeSync(store);
if (import.meta.hot) import.meta.hot.dispose(stopThemeSync);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </Provider>
  </React.StrictMode>,
);
