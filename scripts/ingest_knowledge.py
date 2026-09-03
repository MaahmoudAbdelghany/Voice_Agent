"""
CLI Script to Ingest Domain Knowledge into Qdrant Vector DB.

Usage:
    python -m scripts.ingest_knowledge
    python scripts/ingest_knowledge.py --kb-path knowledge_base/restaurant_kb.md
"""

import sys
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output encoding across all operating systems
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.rag.ingestion import ingestion_pipeline
from src.rag.retriever import retriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("ingest_knowledge")


def main():
    parser = argparse.ArgumentParser(description="Ingest restaurant knowledge into Qdrant")
    parser.add_argument(
        "--kb-path",
        type=str,
        default=str(PROJECT_ROOT / "knowledge_base" / "restaurant_kb.md"),
        help="Path to markdown knowledge base file",
    )
    parser.add_argument(
        "--test-query",
        type=str,
        default="Does the chicken shawarma garlic sauce contain dairy or mayo?",
        help="Test query to verify retrieval after ingestion",
    )
    args = parser.parse_args()

    kb_file = Path(args.kb_path)
    if not kb_file.exists():
        logger.error(f"Knowledge file does not exist: {kb_file}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f"🚀 Ingesting Knowledge Base: {kb_file.name}")
    print("=" * 60)

    count = ingestion_pipeline.ingest_file(kb_file)
    print(f"✅ Successfully ingested {count} knowledge chunks into Qdrant collection '{retriever.collection_name}'.\n")

    # Run verification test query
    print("=" * 60)
    print(f"🔍 Running Sample Retrieval Verification:")
    print(f"Query: '{args.test_query}'")
    print("=" * 60)

    results = retriever.search(query=args.test_query, limit=2)
    for i, res in enumerate(results, start=1):
        print(f"\n[Hit #{i}] Score: {res['score']} | Category: {res['category']} | Section: {res['section']}")
        print("-" * 50)
        print(res["text"][:300] + ("..." if len(res["text"]) > 300 else ""))

    print("\n" + "=" * 60)
    print("🎯 Verification Context Output:")
    print("=" * 60)
    context = retriever.get_context_for_query(args.test_query, limit=2)
    print(context[:400] + "...\n")
    print("✨ Knowledge Base RAG is fully ready and operational!")


if __name__ == "__main__":
    main()
