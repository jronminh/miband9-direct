"""Domain modules: one per field, self-registered via `OPS`.

`register_all(session)` wires every module's `OPS` table into the session
manager's router. Adding a field is a new module plus one line in `DOMAINS`.
"""
from . import data, device, health, notify

DOMAINS = {
    "device": device,
    "notify": notify,
    "health": health,
    "store": data,
}


def register_all(session):
    """Register every domain's ops on `session`; returns the domain names."""
    for domain, module in DOMAINS.items():
        session.register(domain, module.OPS)
    return sorted(DOMAINS)
