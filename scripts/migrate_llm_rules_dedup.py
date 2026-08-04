#!/usr/bin/env python3
"""Migrate llm_rules table: deduplicate by aggregating document_types into JSON array.

Before: 26,970 rows with one document_type per row (13.6× duplication)
After: ~2,000 rows with document_types JSON array

Usage:
    cd fd-cn-report
    python scripts/migrate_llm_rules_dedup.py

This script:
1. Creates a backup table (llm_rules_backup)
2. Adds document_types JSON column
3. Aggregates rows by signature (indicator+module+subgroup+extractor+source_type+...)
4. Drops old document_type column
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import cnreport_database
from sqlalchemy import text


def migrate():
    """Run the deduplication migration."""
    print("=" * 60)
    print("llm_rules Deduplication Migration")
    print("=" * 60)

    db = cnreport_database.get_db()
    session = db.get_session()

    try:
        # Step 1: Check current state
        print("\n[1/6] Checking current state...")
        total_before = session.execute(text("SELECT count(*) FROM llm_rules")).fetchone()[0]
        print(f"  Current rows: {total_before}")

        if total_before == 0:
            print("  No data to migrate, skipping")
            return

        # Step 2: Create backup
        print("\n[2/6] Creating backup table...")
        session.execute(text("DROP TABLE IF EXISTS llm_rules_backup"))
        session.execute(text("CREATE TABLE llm_rules_backup AS SELECT * FROM llm_rules"))
        backup_count = session.execute(text("SELECT count(*) FROM llm_rules_backup")).fetchone()[0]
        print(f"  Backup created: {backup_count} rows")

        # Step 3: Add document_types column
        print("\n[3/6] Adding document_types column...")
        # Check if column already exists
        cols = session.execute(text("PRAGMA table_info(llm_rules)")).fetchall()
        col_names = [c[1] for c in cols]

        if "document_types" not in col_names:
            session.execute(text("ALTER TABLE llm_rules ADD COLUMN document_types TEXT"))
            print("  Added document_types column")
        else:
            print("  document_types column already exists")

        # Step 4: Aggregate document_types by signature
        print("\n[4/6] Aggregating document_types...")

        # Create temp table with aggregated data (without id, will be auto-generated)
        session.execute(text("DROP TABLE IF EXISTS llm_rules_deduped"))
        session.execute(text("""
            CREATE TABLE llm_rules_deduped (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                indicator TEXT,
                module TEXT,
                subgroup TEXT,
                source_type TEXT,
                extractor TEXT,
                applies_to TEXT,
                unit TEXT,
                period_type TEXT,
                value_range TEXT,
                source TEXT,
                aliases TEXT,
                note TEXT,
                direction TEXT,
                instruction TEXT,
                position TEXT,
                document_types TEXT
            )
        """))

        # Insert aggregated data
        session.execute(text("""
            INSERT INTO llm_rules_deduped
            (indicator, module, subgroup, source_type, extractor, applies_to,
             unit, period_type, value_range, source, aliases, note, direction,
             instruction, position, document_types)
            SELECT
                indicator,
                module,
                subgroup,
                source_type,
                extractor,
                applies_to,
                unit,
                period_type,
                value_range,
                source,
                aliases,
                note,
                direction,
                instruction,
                position,
                GROUP_CONCAT(DISTINCT document_type) as document_types
            FROM llm_rules
            GROUP BY indicator, module, subgroup, source_type, extractor,
                     applies_to, unit, period_type, value_range, source,
                     aliases, note, direction, instruction, position
        """))

        deduped_count = session.execute(text("SELECT count(*) FROM llm_rules_deduped")).fetchone()[0]
        print(f"  Deduplicated rows: {deduped_count}")

        # Step 5: Replace original table
        print("\n[5/6] Replacing original table...")
        session.execute(text("DROP TABLE llm_rules"))
        session.execute(text("ALTER TABLE llm_rules_deduped RENAME TO llm_rules"))

        # Convert GROUP_CONCAT string to JSON array
        print("  Converting document_types to JSON array...")
        rows = session.execute(text("SELECT id, document_types FROM llm_rules")).fetchall()
        for row in rows:
            if row.document_types:
                doc_types = row.document_types.split(",")
                session.execute(
                    text("UPDATE llm_rules SET document_types = :dt WHERE id = :id"),
                    {"dt": json.dumps(doc_types, ensure_ascii=False), "id": row.id}
                )

        # Step 6: Verify
        print("\n[6/6] Verifying migration...")
        total_after = session.execute(text("SELECT count(*) FROM llm_rules")).fetchone()[0]
        print(f"  Rows before: {total_before}")
        print(f"  Rows after: {total_after}")
        print(f"  Reduction: {total_before - total_after} rows ({(1 - total_after/total_before)*100:.1f}%)")

        # Sample check
        sample = session.execute(text("""
            SELECT indicator, document_types
            FROM llm_rules
            WHERE indicator = '营业收入'
            LIMIT 1
        """)).fetchone()
        if sample:
            doc_types = json.loads(sample.document_types)
            print(f"\n  Sample: 营业收入")
            print(f"  Appears in {len(doc_types)} document_types")
            print(f"  First 3: {doc_types[:3]}")

        session.commit()

        print("\n" + "=" * 60)
        print("Migration Complete!")
        print("=" * 60)
        print(f"\nBackup table: llm_rules_backup ({backup_count} rows)")
        print("To rollback: DROP TABLE llm_rules; ALTER TABLE llm_rules_backup RENAME TO llm_rules;")

    except Exception as e:
        session.rollback()
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    migrate()
