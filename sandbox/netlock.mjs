// Decides which failed requests the network lock caused (SPEC 5.7), so M5 counts only real blocks.
// The lock REJECTs, so Chrome sees a refused or unreachable connection. Sandboxes reach real sites by
// name, so a lock hit is always to an IP literal (metadata, gateway, VM IP) or localhost.
// Ad blocking, DNS failures, CORS errors and aborted requests are not lock hits.
const LOCK_ERRORS = new Set([
  'net::ERR_CONNECTION_REFUSED',
  'net::ERR_ADDRESS_UNREACHABLE',
  'net::ERR_CONNECTION_RESET',
  'net::ERR_NETWORK_ACCESS_DENIED',
]);

const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;

export function isLockBlock(url, errorText) {
  if (!LOCK_ERRORS.has(errorText)) return false;
  let host;
  try { host = new URL(url).hostname; } catch { return false; }
  return IPV4.test(host) || host.startsWith('[') || host === 'localhost' || host.endsWith('.localhost');
}
