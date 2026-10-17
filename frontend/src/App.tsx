import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";
import { makeQueryClient } from "./api/queries";
import { routes } from "./routes";

// Browser and memory routers share one type.
type Router = ReturnType<typeof createBrowserRouter>;

interface AppProps {
  router?: Router;
  queryClient?: QueryClient;
}

/** The app: data fetching and routing. Tests pass a memory router and their own query client. */
export function App({ router, queryClient }: AppProps) {
  const [client] = useState(() => queryClient ?? makeQueryClient());
  const [activeRouter] = useState(() => router ?? createBrowserRouter(routes));
  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={activeRouter} />
    </QueryClientProvider>
  );
}
