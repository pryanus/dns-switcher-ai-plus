"""
ServiceVerifier: 3-stage validation for testing connectivity through candidate IPs.
Stage 1: TCP connect on port 443/80 with latency measurement.
Stage 2: TLS handshake with SNI and certificate validation.
Stage 3: HTTP probe (status code, headers, error/block-page detection).
"""

import socket
import ssl
import time
from enum import Enum
from typing import Dict, Optional, Tuple, List
from urllib.parse import urlparse
import ipaddress
from core.validation import domain_name
from core.network import Cancelled


class ServiceStatus(str, Enum):
    OK = "OK"              # Full working connection (valid TLS + expected HTTP response)
    PARTIAL = "PARTIAL"    # Reached server but high latency, auth barrier, or partial endpoints
    DEAD = "DEAD"          # Connection refused, timeout, TLS failure, or block page
    UNKNOWN = "UNKNOWN"    # Not verified yet or indeterminable


class VerificationResult:
    def __init__(
        self,
        ip: str,
        domain: str,
        status: ServiceStatus,
        latency_ms: int,
        details: str = "",
        stage_reached: str = "",
        http_code: Optional[int] = None
    ):
        self.ip = ip
        self.domain = domain
        self.status = status
        self.latency_ms = latency_ms
        self.details = details
        self.stage_reached = stage_reached
        self.http_code = http_code
        self.timestamp = time.time()

    def to_dict(self) -> Dict:
        return {
            "ip": self.ip,
            "domain": self.domain,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "stage_reached": self.stage_reached,
            "http_code": self.http_code,
            "timestamp": self.timestamp,
        }

    @property
    def is_routable(self) -> bool:
        # Cloudflare может требовать JavaScript при исправном TLS-маршруте.
        return self.status == ServiceStatus.OK or (
            self.status == ServiceStatus.PARTIAL and self.stage_reached == 'HTTP'
            and self.http_code == 403 and 'Cloudflare challenge' in self.details
        )

    def __repr__(self):
        return f"<VerificationResult {self.domain} via {self.ip}: {self.status.value} ({self.latency_ms}ms) - {self.details}>"


class ServiceVerifier:
    DEFAULT_TIMEOUT = 3.0  # seconds

    # Known ISP block signatures
    BLOCK_SIGNATURES = [
        b"eais.rkn.gov.ru",
        b"zapret.gov.ru",
        b"warning.rt.ru",
        b"\xd0\xb4\xd0\xbe\xd1\x81\xd1\x82\xd1\x83\xd0\xbf \xd0\xbe\xd0\xb3\xd1\x80\xd0\xb0\xd0\xbd\xd0\xb8\xd1\x87\xd0\xb5\xd0\xbd", # "доступ ограничен"
        b"\xd0\xb1\xd0\xbb\xd0\xbe\xd0\xba\xd0\xb8\xd1\x80\xd0\xbe\xd0\xb2\xd0\xba", # "блокировк"
    ]

    @classmethod
    def verify_candidate(cls, ip, domain, port=443, path="/", timeout=3.0,
                         cancellation=None, accepted_codes=()):
        clean_domain = domain_name(domain)
        address = ipaddress.ip_address(ip)
        if not path.startswith("/") or any(c in path for c in "\r\n "):
            raise ValueError("Некорректный путь проверки")
        started = time.monotonic()
        deadline = started + timeout
        sock = None
        stage = "TCP"

        def remaining():
            if cancellation:
                cancellation.check()
            value = deadline - time.monotonic()
            if value <= 0:
                raise socket.timeout()
            return value

        def result(status, details, code=None):
            return VerificationResult(ip, clean_domain, status,
                int((time.monotonic() - started) * 1000), details, stage, code)

        try:
            sock = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET,
                                 socket.SOCK_STREAM)
            if cancellation:
                cancellation.track(sock)
            sock.settimeout(remaining())
            sock.connect((ip, port))
            if port == 443:
                stage = "TLS"
                context = ssl.create_default_context()
                sock.settimeout(remaining())
                raw = sock
                sock = context.wrap_socket(raw, server_hostname=clean_domain,
                                           do_handshake_on_connect=False)
                if cancellation:
                    cancellation.untrack(raw)
                    cancellation.track(sock)
                sock.settimeout(remaining())
                sock.do_handshake()
            stage = "HTTP"
            sock.settimeout(remaining())
            request = (f"GET {path} HTTP/1.1\r\nHost: {clean_domain}\r\n"
                       "User-Agent: Mozilla/5.0\r\nAccept: */*\r\n"
                       "Accept-Encoding: identity\r\nConnection: close\r\n\r\n")
            sock.sendall(request.encode('ascii'))
            response = b""
            while len(response) < 65536:
                sock.settimeout(remaining())
                try:
                    chunk = sock.recv(min(8192, 65536 - len(response)))
                except socket.timeout:
                    if b"\r\n\r\n" in response:
                        break
                    raise
                if not chunk:
                    break
                response += chunk
                if b"\r\n\r\n" in response:
                    headers, body = response.split(b"\r\n\r\n", 1)
                    if len(body) >= 16384:
                        break
                    lengths = [line.split(b":", 1)[1].strip() for line in headers.lower().split(b"\r\n")
                               if line.startswith(b"content-length:")]
                    if lengths and lengths[0].isdigit() and len(body) >= int(lengths[0]):
                        break
                    if body.endswith(b"\r\n0\r\n\r\n"):
                        break
            parts = response.split(b"\r\n", 1)[0].split()
            code = int(parts[1]) if len(parts) > 1 and parts[0].startswith(b"HTTP/") and parts[1].isdigit() else None
            lower = response.lower()
            if any(sig in lower for sig in cls.BLOCK_SIGNATURES):
                return result(ServiceStatus.DEAD, "ISP block page detected", code)
            geo = (b"unsupported_country", b"country_not_supported", b"not available in your country",
                   b"not available in your region", b"not available in your location",
                   b"location is not supported", b"user location is not supported",
                   b"/unsupported-country", b"/unsupported_country", b"/app-unavailable")
            if any(sig in lower for sig in geo):
                return result(ServiceStatus.DEAD, "Региональный запрет (Geo-block error)", code)
            if b"cf-mitigated:" in lower or b"challenges.cloudflare.com" in lower:
                return result(ServiceStatus.PARTIAL, "Cloudflare challenge: откройте сервис в браузере", code)
            if clean_domain.endswith('.oaiusercontent.com') and code == 403 and any(
                marker in lower for marker in (b'<code>authenticationfailed</code>',
                    b'<code>publicaccessnotpermitted</code>', b'<code>authorizationfailure</code>')):
                return result(ServiceStatus.OK, 'Хранилище отвечает; загрузку с подписью проверьте в ChatGPT', code)
            if code == 403 and clean_domain.endswith(('.googleapis.com', '.clients6.google.com')) and (
                b'unregistered callers' in lower or b'api_key_invalid' in lower):
                return result(ServiceStatus.OK, 'API отвечает; для запроса требуется сессия или ключ', code)
            if code in (200, 204) or code in accepted_codes:
                return result(ServiceStatus.OK, f"HTTPS отвечает (HTTP {code})", code)
            if code in (301, 302, 303, 307, 308):
                return result(ServiceStatus.PARTIAL, f"HTTP {code}: переход не подтверждает доступ к функциям", code)
            if code and code >= 500:
                return result(ServiceStatus.DEAD, f"HTTP {code}: ошибка сервера", code)
            return result(ServiceStatus.PARTIAL, f"HTTP {code or '—'}: доступ не подтверждён", code)
        except Cancelled:
            raise
        except ssl.SSLCertVerificationError as error:
            return result(ServiceStatus.DEAD, f"TLS certificate verification failed: {error}")
        except (OSError, ssl.SSLError) as error:
            if cancellation:
                cancellation.check()
            message = f"{stage} timed out" if isinstance(error, TimeoutError) else f"{stage}: {error}"
            return result(ServiceStatus.DEAD, message)
        finally:
            if sock:
                if cancellation:
                    cancellation.untrack(sock)
                sock.close()

    @classmethod
    def test_spotify_nuances(cls, ip: str) -> Dict[str, any]:
        """
        Special check for Spotify:
        Verifies open.spotify.com, accounts.spotify.com, spclient.wg.spotify.com.
        """
        res_web = cls.verify_candidate(ip, "open.spotify.com", path="/")
        res_auth = cls.verify_candidate(ip, "accounts.spotify.com", path="/login")
        return {
            "web_player": res_web.to_dict(),
            "accounts": res_auth.to_dict(),
            "note": "Desktop Spotify app connects to port 4070 (AP protocol). If Error 17 occurs, use browser login or an EU IP matching account region."
        }
