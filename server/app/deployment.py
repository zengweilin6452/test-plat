"""Deployment identity checks shared by startup and demo seeding."""
import ipaddress

from urllib.parse import parse_qs, unquote, urlsplit


def is_formal_database(value: str) -> bool:
    """Ignore credentials, driver and harmless query options when identifying a DB.

    libpq query parameters can override URL host/port/dbname, so inspect the
    effective target and reject ambiguous multi-host and socket targets.
    """
    try:
        url = urlsplit(value)
        if url.scheme.split("+")[0] not in {"postgresql", "postgres"}:
            return True
        query = parse_qs(url.query)
        if "service" in query:
            return True
        host = query.get("hostaddr", query.get("host", [url.hostname or "localhost"]))[-1].lower().rstrip(".")
        port = int(query.get("port", [url.port or 5432])[-1])
        database = query.get("dbname", [unquote(url.path.lstrip("/"))])[-1]
        if not database or "," in host or "/" in host or "\\" in host:
            return True
        try:
            address = ipaddress.ip_address(host)
            loopback = address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
        except ValueError:
            loopback = host == "localhost"
        return loopback and port == 55432 and database == "testdock"
    except (ValueError, TypeError):
        return True
