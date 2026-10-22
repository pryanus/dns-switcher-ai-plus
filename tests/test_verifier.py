import unittest
from unittest.mock import patch, MagicMock
import socket
import ssl
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.verifier import ServiceVerifier, ServiceStatus


class TestServiceVerifier(unittest.TestCase):
    def test_tcp_timeout_classification(self):
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = socket.timeout("timed out")
            mock_sock_cls.return_value = mock_sock

            result = ServiceVerifier.verify_candidate("192.0.2.1", "chatgpt.com", timeout=0.1)
            self.assertEqual(result.status, ServiceStatus.DEAD)
            self.assertIn("timed out", result.details.lower())
            self.assertEqual(result.stage_reached, "TCP")

    def test_tls_cert_error_classification(self):
        with patch("socket.socket") as mock_sock_cls, \
             patch("ssl.create_default_context") as mock_ssl_ctx_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value = mock_sock

            mock_ctx = MagicMock()
            mock_ssl_ctx_cls.return_value = mock_ctx
            mock_ctx.wrap_socket.side_effect = ssl.SSLCertVerificationError("Certificate verification failed")

            result = ServiceVerifier.verify_candidate("193.233.112.68", "chatgpt.com", timeout=0.5)
            self.assertEqual(result.status, ServiceStatus.DEAD)
            self.assertIn("certificate verification failed", result.details.lower())
            self.assertEqual(result.stage_reached, "TLS")

    def test_http_200_ok_classification(self):
        with patch("socket.socket") as mock_sock_cls, \
             patch("ssl.create_default_context") as mock_ssl_ctx_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value = mock_sock

            mock_tls = MagicMock()
            mock_tls.recv.side_effect = [
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<!DOCTYPE html><html>",
                b""
            ]
            mock_ctx = MagicMock()
            mock_ssl_ctx_cls.return_value = mock_ctx
            mock_ctx.wrap_socket.return_value = mock_tls

            result = ServiceVerifier.verify_candidate("193.233.112.68", "chatgpt.com", timeout=0.5)
            self.assertEqual(result.status, ServiceStatus.OK)
            self.assertEqual(result.http_code, 200)
            self.assertEqual(result.stage_reached, "HTTP")

    def test_cloudflare_widget_and_csp_are_not_challenge_pages(self):
        for response in (
            b'HTTP/1.1 200 OK\r\nContent-Security-Policy: frame-src https://challenges.cloudflare.com\r\n\r\n<title>OpenRouter</title>',
            b'HTTP/1.1 200 OK\r\n\r\n<title>Notion</title><script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
        ):
            with self.subTest(response=response), patch('socket.socket'), patch('ssl.create_default_context') as context:
                context.return_value.wrap_socket.return_value.recv.side_effect = [response, b'']
                result = ServiceVerifier.verify_candidate('1.1.1.1', 'example.com')
                self.assertEqual(result.status, ServiceStatus.OK)
                self.assertFalse(result.is_browser_challenge)

    def test_real_cloudflare_challenge_is_never_routable(self):
        with patch('socket.socket'), patch('ssl.create_default_context') as context:
            context.return_value.wrap_socket.return_value.recv.side_effect = [
                b'HTTP/1.1 403 Forbidden\r\ncf-mitigated: challenge\r\n\r\n<title>Just a moment...</title>', b'']
            result = ServiceVerifier.verify_candidate('1.1.1.1', 'example.com')
            self.assertTrue(result.is_browser_challenge)
            self.assertFalse(result.is_routable)

    def test_accepted_redirect_is_followed_and_blocked_landing_rejected(self):
        with patch('socket.socket'), patch('ssl.create_default_context') as context:
            first, second = MagicMock(), MagicMock()
            context.return_value.wrap_socket.side_effect = [first, second]
            first.recv.side_effect = [b'HTTP/1.1 302 Found\r\nLocation: /login\r\nContent-Length: 0\r\n\r\n']
            second.recv.side_effect = [b'HTTP/1.1 200 OK\r\n\r\nNot available in your country', b'']
            result = ServiceVerifier.verify_candidate('1.1.1.1', 'example.com', accepted_codes=(302,))
            self.assertEqual(result.status, ServiceStatus.DEAD)
            self.assertIn('Geo-block', result.details)

    def test_isp_block_classification(self):
        with patch("socket.socket") as mock_sock_cls, \
             patch("ssl.create_default_context") as mock_ssl_ctx_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value = mock_sock

            mock_tls = MagicMock()
            mock_tls.recv.side_effect = [
                b"HTTP/1.1 200 OK\r\nLocation: http://eais.rkn.gov.ru/\r\n\r\n",
                b""
            ]
            mock_ctx = MagicMock()
            mock_ssl_ctx_cls.return_value = mock_ctx
            mock_ctx.wrap_socket.return_value = mock_tls

            result = ServiceVerifier.verify_candidate("1.2.3.4", "example.com", timeout=0.5)
            self.assertEqual(result.status, ServiceStatus.DEAD)
            self.assertIn("block page", result.details.lower())


if __name__ == "__main__":
    unittest.main()
