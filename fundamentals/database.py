"""
Supabase data access helpers for the ReScanX stock fundamentals pipeline.
Handles connection, fetching, upserting, and schema management.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency
    psycopg = None

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

DEFAULT_TABLE_NAME = "stock_fundamentals"
SQL_EXECUTOR_FN_ENV = "SUPABASE_SQL_FUNCTION"
SQL_EXECUTOR_DEFAULT = "exec_sql"


class SupabaseManager:
    """Lightweight wrapper around supabase-py operations."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        key: Optional[str] = None,
        table: str = DEFAULT_TABLE_NAME,
        database_url: Optional[str] = None,
    ) -> None:
        self.url = url or os.getenv("SUPABASE_URL")
        service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        anon_key = os.getenv("SUPABASE_ANON_KEY")
        self.key = key or service_key or anon_key
        
        # If no credentials found, we can't function
        if not self.url or not self.key:
            raise ValueError("Supabase credentials are missing. Set SUPABASE_URL and a key env var.")

        self.table = table
        self.client: Client = create_client(self.url, self.key)
        self.database_url = database_url or os.getenv("SUPABASE_DB_URL")

    # ------------------------------------------------------------------
    # SQL helpers
    # ------------------------------------------------------------------
    def execute_sql(self, statement: str) -> None:
        """Run a raw SQL statement via psycopg or a configurable RPC function.
        
        Useful for schema migrations or complex queries not supported by the JS client.
        """
        if not statement.strip():
            return

        # Prefer direct connection if available (faster/more control)
        if self.database_url and psycopg is not None:
            try:
                with psycopg.connect(self.database_url, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute(statement)
                return
            except Exception:
                # Fallback to RPC if direct connection fails
                pass

        # Fallback: Supabase RPC (Remote Procedure Call)
        function_name = os.getenv(SQL_EXECUTOR_FN_ENV, SQL_EXECUTOR_DEFAULT)
        response = self.client.postgrest.rpc(function_name, {"query": statement}).execute()
        
        # Check for errors in response if using an older client version
        if getattr(response, "error", None):
            raise RuntimeError(f"Supabase RPC '{function_name}' failed: {response.error}")

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------
    def fetch_ticker(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch the full record for a specific ticker."""
        try:
            response = (
                self.client
                .table(self.table)
                .select("*")
                .eq("ticker", ticker)
                .limit(1)
                .execute()
            )
            data = getattr(response, "data", None) or []
            return data[0] if data else None
        except Exception:
            return None

    def upsert_record(self, payload: Dict[str, Any]) -> None:
        """Insert or Update a stock record based on the 'ticker' key."""
        if "ticker" not in payload:
            raise ValueError("Payload must include a 'ticker' key for upsert.")
        
        # Ensure we stamp the update time
        payload.setdefault("last_updated", datetime.now(timezone.utc).isoformat())
        
        # Perform upsert
        self.client.table(self.table).upsert(payload, on_conflict="ticker").execute()

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    @staticmethod
    def needs_refresh(record: Dict[str, Any], *, hours: int = 24) -> bool:
        """Check if the data is stale (older than 'hours')."""
        last_updated = record.get("last_updated")
        
        # If no timestamp, it's definitely stale
        if not last_updated:
            return True
            
        try:
            timestamp = datetime.fromisoformat(str(last_updated))
        except ValueError:
            return True
            
        # Ensure timezone awareness for comparison
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
            
        return datetime.now(timezone.utc) - timestamp > timedelta(hours=hours)