import { createContext, useContext } from "react";

export const PublicTransitionContext = createContext(null);

export function usePublicPageTransition() {
  return useContext(PublicTransitionContext);
}
