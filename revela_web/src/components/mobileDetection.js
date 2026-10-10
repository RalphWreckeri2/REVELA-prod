const MOBILE_USER_AGENT =
  /Android|iPhone|iPad|iPod|Mobile|Windows Phone|Tablet/i;

export function isMobileBrowser() {
  return typeof navigator !== "undefined" && MOBILE_USER_AGENT.test(navigator.userAgent);
}
