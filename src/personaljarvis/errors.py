"""Geschlossene technische Fehlerklassen von Personal Jarvis.

Die Menge ist bewusst klein und abgeschlossen (08 §3 Nr. 5): Aufrufer sollen
auf einen Typ prüfen können, nicht auf Zeichenketten. **Keine dieser Meldungen
enthält jemals Kontaktdaten** — weder Namen, Adressen, Nummern noch Identifier
eines Providers. Diagnosetexte beschreiben ausschließlich Technik.
"""

from __future__ import annotations

__all__ = [
    "PersonalJarvisError",
    "ConfigurationError",
    "DatabaseError",
    "SchemaError",
    "MigrationError",
    "LedgerError",
    "IntegrityError",
    "TransactionError",
    "CapabilityError",
]


class PersonalJarvisError(Exception):
    """Wurzel aller Personal-Jarvis-Fehler."""


class ConfigurationError(PersonalJarvisError):
    """Konfiguration fehlt, widerspricht sich oder ist unbrauchbar."""


class DatabaseError(PersonalJarvisError):
    """Die kanonische Datenbank ist nicht in einem benutzbaren Zustand."""


class SchemaError(DatabaseError):
    """Das Schema entspricht nicht der erwarteten Form."""


class MigrationError(DatabaseError):
    """Eine Migration ist fehlgeschlagen oder nicht ausführbar."""


class LedgerError(MigrationError):
    """Das Migrations-Ledger ist unstimmig — fail-closed (07 §6 Nr. 2)."""


class IntegrityError(DatabaseError):
    """Eine Integritätsbedingung der kanonischen Daten wurde verletzt."""


class TransactionError(DatabaseError):
    """Eine UnitOfWork wurde vertragswidrig benutzt."""


class CapabilityError(PersonalJarvisError):
    """Eine Fähigkeit wurde verlangt, die der Provider nicht deklariert."""
