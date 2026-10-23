# API request rate limits

The backend applies a process-local sliding-window request limit to API
requests. Defaults are 300 requests per client IP per minute, with stricter
limits for public authentication endpoints:

- Login: 10 requests per 5 minutes.
- 2FA login verification: 10 requests per 15 minutes.
- OTP request: 5 requests per 15 minutes, in addition to the existing
  per-account daily limit.
- Manual password-reset request: 3 requests per hour.
- Password reset: 10 requests per 15 minutes.

Rejected requests return HTTP 429 with a `Retry-After` header. `OPTIONS`
preflight requests are excluded. Limits can be adjusted through the matching
`API_RATE_*` and `AUTH_*_RATE_*` environment variables.

The client IP comes from the WSGI `REMOTE_ADDR` by default; forwarded headers
are not trusted by default. Set `TRUSTED_PROXY_COUNT` only when the backend is
reachable exclusively through a known number of trusted proxies that replace
the forwarded client-IP header. Incorrect proxy configuration can make clients
share a proxy IP or allow spoofed addresses.

This in-process limiter is an application safeguard, not DDoS mitigation. It
does not share counters across replicas and cannot absorb traffic that already
exhausts network or hosting capacity. Keep edge/WAF/provider-level rate limits
and DDoS protection enabled for the deployed service; configure them in the
hosting environment.
