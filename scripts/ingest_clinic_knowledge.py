"""
CLI Ingestion Pipeline for Egyptian Polyclinic Knowledge Base.

Parses clinic_kb.md, generates multilingual FastEmbed dense vectors,
and indexes categorized chunks into Qdrant collection ('clinic_kb').
Supports collection recreation and instant retrieval verification.
"""

import argparse
import io
import logging
import sys
import time
from collections import Counter
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr is not None:
            sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass

# Add workspace root to sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from src.rag.embeddings import embedding_service
from src.rag.ingestion import ingestion_pipeline
from src.rag.retriever import retriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_clinic_knowledge")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Ingest Egyptian Polyclinic Knowledge Base into Qdrant vector store."
    )
    parser.add_argument(
        "--kb-path",
        type=str,
        default="knowledge_base/clinic_kb.md",
        help="Path to the clinic knowledge base markdown document (default: knowledge_base/clinic_kb.md)",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate the Qdrant collection from scratch before indexing.",
    )
    parser.add_argument(
        "--test-query",
        type=str,
        default=None,
        help="Optional test query to verify semantic retrieval immediately after ingestion.",
    )
    return parser.parse_args()


def main() -> None:
    """Execute the clinic knowledge base ingestion and verification."""
    args = parse_args()
    kb_path = Path(args.kb_path)
    if not kb_path.is_absolute():
        kb_path = WORKSPACE_ROOT / kb_path

    if not kb_path.exists():
        sys.stderr.write(f"Error: Knowledge base file not found at '{kb_path}'\n")
        sys.exit(1)

    if not embedding_service.is_semantic:
        sys.stderr.write(
            "Error: EmbeddingService is running in fallback mode (model failed to load). "
            "Refusing to ingest chunks to prevent corrupting collection with pseudo-embeddings.\n"
        )
        sys.exit(1)

    print("=" * 65)
    print("🏥 مجمع عيادات النور التخصصي — خط أنابيب استيعاب قاعدة المعرفة")
    print("   Egyptian Polyclinic Qdrant Ingestion & Verification CLI")
    print("=" * 65)
    print(f"📄 Knowledge Base File : {kb_path}")
    print(f"📦 Target Collection   : {retriever.collection_name}")
    print(f"🔄 Recreate Collection : {args.recreate}")
    print("-" * 65)

    # Recreate collection if requested
    if args.recreate:
        print(f"🗑️ Recreating collection '{retriever.collection_name}'...")
        retriever.recreate_collection()
        print("✅ Collection recreated successfully.")

    # Parse markdown into structured chunks
    print("🔍 Parsing markdown document into semantic chunks...")
    chunks = ingestion_pipeline.parse_markdown(kb_path)
    if not chunks:
        sys.stderr.write("Error: No chunks extracted from knowledge base file.\n")
        sys.exit(1)

    total_chunks = len(chunks)
    category_counts = Counter(chunk["metadata"]["category"] for chunk in chunks)

    print(f"📊 Parsed {total_chunks} chunks across {len(category_counts)} categories:")
    for cat, count in sorted(category_counts.items()):
        print(f"   • {cat:<18}: {count} chunk(s)")

    # Ingest and embed chunks into Qdrant
    print("-" * 65)
    print("⚡ Generating FastEmbed embeddings and upserting into Qdrant...")
    start_time = time.perf_counter()
    indexed_count = retriever.upsert_chunks(chunks)
    elapsed = time.perf_counter() - start_time
    print(f"✅ Upserted {indexed_count} points in {elapsed:.2f} seconds.")

    # Run verification test query if requested
    test_query = args.test_query
    if test_query:
        print("=" * 65)
        print("🧪 Testing Retrieval Verification for query:")
        print(f'   ❓ "{test_query}"')
        print("-" * 65)
        hits = retriever.search(query=test_query, limit=3)
        if not hits:
            print("⚠️ No matching points found for test query.")
        else:
            print(f"🎯 Found {len(hits)} matching result(s):")
            for idx, hit in enumerate(hits, start=1):
                snippet = hit["text"][:140].replace("\n", " ") + "..."
                print(
                    f"   [{idx}] Score: {hit['score']:.4f} | "
                    f"Category: {hit['category']} | "
                    f"Section: {hit['section']}"
                )
                print(f"       Snippet: {snippet}")

    print("=" * 65)
    print("🎉 Knowledge Ingestion Pipeline completed successfully!")
    print("=" * 65)
    sys.exit(0)


if __name__ == "__main__":
    main()
