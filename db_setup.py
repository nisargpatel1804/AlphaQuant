"""One-off Supabase migration script for the stock fundamentals table."""
from __future__ import annotations

from db_manager import SupabaseManager

SCHEMA_STATEMENTS = [
    # Enable pgcrypto for UUID generation if not already enabled
    'create extension if not exists "pgcrypto";',
    
    # Create the main table with JSONB columns for flexible data storage
    # Added 'industry_pe' to explicit columns to match the updated scraper logic
    """
    create table if not exists public.stock_fundamentals (
        id uuid primary key default gen_random_uuid(),
        ticker text not null unique,
        last_updated timestamptz not null default timezone('utc', now()),
        metadata jsonb not null default '{}'::jsonb,
        market_cap double precision,
        current_price double precision,
        high_price double precision,
        low_price double precision,
        stock_pe double precision,
        industry_pe double precision,
        book_value double precision,
        dividend_yield double precision,
        roce double precision,
        roe double precision,
        face_value double precision,
        quarterly_results jsonb not null default '{}'::jsonb,
        profit_loss_annual jsonb not null default '{}'::jsonb,
        balance_sheet jsonb not null default '{}'::jsonb,
        cash_flow jsonb not null default '{}'::jsonb,
        ratios jsonb not null default '{}'::jsonb,
        shareholding jsonb not null default '{}'::jsonb
    );
    """,
    
    # Create index for fast lookups by ticker
    'create unique index if not exists idx_stock_fundamentals_ticker on public.stock_fundamentals (ticker);',
]


def initialize_schema() -> None:
    """Run the schema creation statements against Supabase."""
    manager = SupabaseManager()
    print("Initializing database schema...")
    for statement in SCHEMA_STATEMENTS:
        try:
            manager.execute_sql(statement)
        except Exception as e:
            print(f"Error executing statement: {e}")
            # Continue to next statement (e.g. if extension already exists)
    print("Schema initialization complete.")


def main() -> None:
    initialize_schema()


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    main()