"""Fehlerklassen des GoCoax-Clients."""

from __future__ import annotations


class GoCoaxError(Exception):
    """Basisklasse fuer alle Fehler dieses Clients."""


class GoCoaxAuthError(GoCoaxError):
    """Basic Auth wurde abgelehnt (HTTP 401)."""


class GoCoaxCsrfError(GoCoaxError):
    """CSRF-Token fehlt oder wird auch nach einem Refresh nicht akzeptiert."""
