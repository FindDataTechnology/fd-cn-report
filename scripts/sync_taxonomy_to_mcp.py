#!/usr/bin/env python3
"""Sync taxonomy system to fd-open-data-mcp.

This script registers taxonomy concepts and entities in the fd-open-data-mcp
ontology store, enabling taxonomy-based queries through the MCP interface.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "fd-open-data-mcp"))


def sync_taxonomy_to_mcp():
    """Register taxonomy concepts and entities in fd-open-data-mcp."""
    from fd_open_data_mcp.models import Concept, ConceptBinding, Entity, EntityRelationship
    from fd_open_data_mcp.db import get_database
    import rules_db

    print("=" * 70)
    print("Syncing Taxonomy to fd-open-data-mcp")
    print("=" * 70)

    db = get_database()
    session = db.get_session()

    try:
        # Get taxonomy data
        report_taxonomy = rules_db.list_report_taxonomy()
        document_taxonomy = rules_db.list_document_taxonomy()

        print(f"\nReport Taxonomy entries: {len(report_taxonomy)}")
        print(f"Document Taxonomy entries: {len(document_taxonomy)}")

        # 1. Register report taxonomy as concepts
        print("\n[1/4] Registering report taxonomy concepts...")
        report_concept_count = 0
        for entry in report_taxonomy:
            code = f"taxonomy.{entry['code']}"
            # Check if concept already exists
            existing = session.query(Concept).filter(
                Concept.code == code,
                Concept.entity_type == "industry"
            ).first()

            if not existing:
                concept = Concept(
                    code=code,
                    name_en=entry.get('label_en'),
                    name_zh=entry.get('label_zh'),
                    category="report_taxonomy",
                    unit="string",
                    measure="report_section_classification",
                    frequency="static",
                    entity_type="industry",
                    source="fd-cn-report",
                    verified=True
                )
                session.add(concept)
                report_concept_count += 1

        print(f"  ✓ Added {report_concept_count} report taxonomy concepts")

        # 2. Register document taxonomy as concepts
        print("\n[2/4] Registering document taxonomy concepts...")
        doc_concept_count = 0
        for entry in document_taxonomy:
            code = f"taxonomy.doc.{entry['code']}"
            existing = session.query(Concept).filter(
                Concept.code == code,
                Concept.entity_type == "organization"
            ).first()

            if not existing:
                concept = Concept(
                    code=code,
                    name_en=entry.get('label_en'),
                    name_zh=entry.get('label_zh'),
                    category="document_taxonomy",
                    unit="array",
                    measure="document_type_classification",
                    frequency="static",
                    entity_type="organization",
                    source="fd-cn-report",
                    verified=True
                )
                session.add(concept)
                doc_concept_count += 1

        print(f"  ✓ Added {doc_concept_count} document taxonomy concepts")

        # 3. Register taxonomy entities
        print("\n[3/4] Registering taxonomy entities...")
        entity_count = 0

        # Report taxonomy entities
        for entry in report_taxonomy[:20]:  # Top 20
            code = f"taxonomy_{entry['code']}"
            existing = session.query(Entity).filter(
                Entity.code == code,
                Entity.entity_type == "industry"
            ).first()

            if not existing:
                entity = Entity(
                    entity_type="industry",
                    code=code,
                    name_en=entry.get('label_en'),
                    name_zh=entry.get('label_zh'),
                    metadata={
                        "classification_system": "report_taxonomy",
                        "level": entry.get('level', 1),
                        "parent_code": entry.get('parent_code'),
                    }
                )
                session.add(entity)
                entity_count += 1

        # Document taxonomy entities
        for entry in document_taxonomy:
            code = f"doc_{entry['code']}"
            existing = session.query(Entity).filter(
                Entity.code == code,
                Entity.entity_type == "organization"
            ).first()

            if not existing:
                entity = Entity(
                    entity_type="organization",
                    code=code,
                    name_en=entry.get('label_en'),
                    name_zh=entry.get('label_zh'),
                    metadata={
                        "classification_system": "document_taxonomy",
                        "country": entry.get('country'),
                        "exchange": entry.get('exchange'),
                        "report_kind": entry.get('report_kind'),
                    }
                )
                session.add(entity)
                entity_count += 1

        print(f"  ✓ Added {entity_count} taxonomy entities")

        # 4. Create concept bindings for taxonomy columns
        print("\n[4/4] Creating concept bindings...")
        binding_count = 0

        # Find fd-cn-report functions
        from fd_open_data_mcp.models import Function, FunctionColumn
        cn_report_functions = session.query(Function).filter(
            Function.command.like('%cn_report%')
        ).all()

        for func in cn_report_functions:
            # Bind taxonomy_code column
            taxonomy_col = session.query(FunctionColumn).filter(
                FunctionColumn.function_id == func.id,
                FunctionColumn.name == "taxonomy_code"
            ).first()

            if taxonomy_col:
                concept_code = "taxonomy.report_section"
                concept = session.query(Concept).filter(
                    Concept.code == concept_code,
                    Concept.entity_type == "industry"
                ).first()

                if concept:
                    existing_binding = session.query(ConceptBinding).filter(
                        ConceptBinding.column_id == taxonomy_col.id,
                        ConceptBinding.concept_id == concept.id
                    ).first()

                    if not existing_binding:
                        binding = ConceptBinding(
                            column_id=taxonomy_col.id,
                            concept_id=concept.id,
                            confidence=0.95,
                            provenance="fd-cn-report-taxonomy"
                        )
                        session.add(binding)
                        binding_count += 1

        print(f"  ✓ Created {binding_count} concept bindings")

        # Commit all changes
        session.commit()

        print("\n" + "=" * 70)
        print("✅ Sync complete!")
        print("=" * 70)
        print(f"\nSummary:")
        print(f"  Report taxonomy concepts: {report_concept_count}")
        print(f"  Document taxonomy concepts: {doc_concept_count}")
        print(f"  Taxonomy entities: {entity_count}")
        print(f"  Concept bindings: {binding_count}")

        print("\nNext steps:")
        print("1. Test taxonomy queries through MCP")
        print("2. Verify concept search works with taxonomy codes")
        print("3. Update documentation with MCP query examples")

    except Exception as e:
        session.rollback()
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    sync_taxonomy_to_mcp()
