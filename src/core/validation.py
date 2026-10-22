"""Проверка данных перед сетевыми запросами и записью hosts."""
import ipaddress
import re


def domain_name(value: str) -> str:
    value = value.strip().rstrip('.').encode('idna').decode('ascii').lower()
    if len(value) > 253 or '.' not in value or not all(
        re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part)
        for part in value.split('.')
    ):
        raise ValueError('Некорректное доменное имя')
    return value


def public_ip(value: str) -> str:
    address = ipaddress.ip_address(value.strip())
    if not address.is_global:
        raise ValueError('Нужен публичный IP-адрес')
    return str(address)


def parse_hosts(text: str) -> dict:
    mappings = {}
    for line in text.splitlines():
        parts = line.partition('#')[0].split()
        if len(parts) < 2:
            continue
        try:
            ip = public_ip(parts[0])
        except ValueError:
            continue
        for raw_domain in parts[1:]:
            try:
                domain = domain_name(raw_domain)
            except (ValueError, UnicodeError):
                continue
            if ip not in mappings.setdefault(domain, []):
                mappings[domain].append(ip)
    return mappings
