"""Fetch a public document and render its HTML as an offline screenshot."""

import http.client
import ipaddress
import os
import socket
import ssl
from time import monotonic
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

MAX_BYTES = 1_048_576
OFFLINE_POLICY = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    'style-src \'unsafe-inline\'; img-src data:; frame-src \'none\'; '
    'form-action \'none\'; base-uri \'none\'">'
)
REDIRECTS = {301, 302, 303, 307, 308}


class CaptureError(Exception):
    """The submitted page could not be captured."""


def public_address(host, port):
    addresses = [entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
    if not addresses:
        raise CaptureError("This host does not resolve.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if (not ip.is_global or ip.is_multicast or ip.is_reserved
                or isinstance(ip, ipaddress.IPv6Address) and (ip.sixtofour or ip.teredo or ip.is_site_local)):
            raise CaptureError("Only publicly reachable web addresses can be captured.")
    return addresses[0]


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, 443, timeout=5, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def fetch_document(url):
    for _ in range(5):
        parts = urlsplit(url)
        port = {"https": 443, "http": 80}.get(parts.scheme)
        if port is None or not parts.hostname or parts.username is not None or parts.port not in {None, port}:
            raise CaptureError("Use an HTTP or HTTPS link with a standard port and no credentials.")
        host = parts.hostname.encode("idna").decode("ascii")
        address = public_address(host, port)
        if parts.scheme == "https":
            connection = PublicHTTPSConnection(host, address)
        else:
            connection = http.client.HTTPConnection(address, port, timeout=5)
        target = urlunsplit(("", "", quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                             quote(parts.query, safe="/%:@!$&'()*+,;=?-._~"), ""))
        host_header = f"[{host}]" if ":" in host else host
        try:
            connection.request("GET", target, headers={
                "Host": host_header, "Accept": "text/html, application/xhtml+xml",
                "Accept-Encoding": "identity", "User-Agent": "PhishDetonator-PassiveCapture/1.0",
            })
            response = connection.getresponse()
            if response.status in REDIRECTS and response.getheader("Location"):
                url = urljoin(url, response.getheader("Location"))
                continue
            if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
                raise CaptureError(f"The site returned HTTP {response.status} without an HTML page to capture.")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise CaptureError("The page returned an unsupported encoding.")
            deadline = monotonic() + 6
            data = bytearray()
            while len(data) <= MAX_BYTES and monotonic() < deadline:
                chunk = response.read1(min(65_536, MAX_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            else:
                if len(data) <= MAX_BYTES:
                    raise CaptureError("The page took too long to download.")
            if len(data) > MAX_BYTES:
                raise CaptureError("The page is too large to capture.")
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                return url, response.status, data.decode(encoding, errors="replace")
            except LookupError:
                return url, response.status, data.decode("utf-8", errors="replace")
        finally:
            connection.close()
    raise CaptureError("The link redirected too many times.")


def capture_url(url):
    try:
        final_url, http_status, html = fetch_document(url)
    except CaptureError:
        raise
    except ssl.SSLCertVerificationError as error:
        raise CaptureError("The page’s HTTPS certificate could not be verified.") from error
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise CaptureError("The public page could not be reached.") from error

    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as error:
        raise CaptureError("Screenshot support requires Playwright and Chromium on the server.") from error

    try:
        with sync_playwright() as playwright:
            executable = os.getenv("PD_CAPTURE_CHROME")
            browser = playwright.chromium.launch(executable_path=executable, chromium_sandbox=True,
                                                 timeout=10_000)
            try:
                context = browser.new_context(java_script_enabled=False, offline=True, accept_downloads=False,
                                              service_workers="block", viewport={"width": 1280, "height": 800})
                context.route("**/*", lambda route: route.abort())
                page = context.new_page()
                page.set_content(OFFLINE_POLICY + html, wait_until="domcontentloaded", timeout=8_000)
                return final_url, page.title(), page.screenshot(timeout=8_000), http_status
            finally:
                browser.close()
    except Error as error:
        raise CaptureError("Chromium could not render this page offline.") from error
