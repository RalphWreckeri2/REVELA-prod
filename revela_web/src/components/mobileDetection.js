const MOBILE_USER_AGENT = /iPhone|iPod|Mobile|Windows Phone/i;

export function isMobileBrowser() {
  if (typeof navigator === "undefined") {
    return false;
  }

  return (
    navigator.userAgentData?.mobile === true ||
    MOBILE_USER_AGENT.test(navigator.userAgent)
  );
}
