"""
Unit and Integration Tests for RAG Knowledge Base & Vector Retriever.
"""

from pathlib import Path
import pytest
from src.rag.embeddings import EmbeddingService
from src.rag.retriever import QdrantKnowledgeRetriever
from src.rag.ingestion import KnowledgeIngestionPipeline


@pytest.fixture
def embedding_service():
    return EmbeddingService()


@pytest.fixture
def local_retriever():
    # Force fresh in-memory collection for test isolation
    test_retriever = QdrantKnowledgeRetriever(collection_name="test_restaurant_kb")
    return test_retriever


def test_embedding_generation(embedding_service):
    """Test generating embeddings for query and batch documents."""
    assert embedding_service.dimension == 384

    query_vec = embedding_service.embed_query("Chicken shawarma wrap")
    assert isinstance(query_vec, list)
    assert len(query_vec) == 384
    assert any(x != 0.0 for x in query_vec)

    doc_vecs = embedding_service.embed_documents(["Shawarma", "Falafel plate"])
    assert len(doc_vecs) == 2
    assert len(doc_vecs[0]) == 384
    assert len(doc_vecs[1]) == 384


def test_retriever_upsert_and_search(local_retriever):
    """Test indexing and semantic searching in in-memory Qdrant."""
    sample_chunks = [
        {
            "id": "item_shawarma",
            "text": "Chicken Shawarma Wrap is $9.99 made with Saj bread and garlic toum.",
            "metadata": {"category": "menu", "section": "Shawarma Specialties"},
        },
        {
            "id": "item_delivery",
            "text": "Delivery fee is $3.99 within 5 miles, free for orders above $45.",
            "metadata": {"category": "delivery", "section": "Delivery Policies"},
        },
        {
            "id": "item_allergen",
            "text": "Toum garlic sauce is completely dairy-free and egg-free.",
            "metadata": {"category": "allergens", "section": "Dietary Guidelines"},
        },
    ]

    count = local_retriever.upsert_chunks(sample_chunks)
    assert count == 3

    # Test search for garlic sauce
    results = local_retriever.search("Does garlic sauce have dairy?", limit=2)
    assert len(results) > 0
    top_hit = results[0]
    assert "dairy-free" in top_hit["text"] or "garlic" in top_hit["text"]
    assert top_hit["score"] is not None

    # Test category filter
    delivery_results = local_retriever.search("delivery", category="delivery")
    assert len(delivery_results) >= 1
    assert delivery_results[0]["category"] == "delivery"

    # Test context string formatting
    context = local_retriever.get_context_for_query("garlic sauce")
    assert isinstance(context, str)
    assert len(context) > 0


def test_knowledge_ingestion_pipeline():
    """Test parsing of the actual restaurant_kb.md file."""
    kb_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "restaurant_kb.md"
    assert kb_path.exists(), "restaurant_kb.md must exist"

    pipeline = KnowledgeIngestionPipeline()
    chunks = pipeline.parse_markdown(kb_path)
    
    assert len(chunks) >= 5, f"Expected at least 5 chunks, found {len(chunks)}"

    categories = {chunk["metadata"]["category"] for chunk in chunks}
    assert "menu" in categories
    assert "allergens" in categories
    assert "delivery" in categories

    # Verify end-to-end ingestion into in-memory retriever
    test_retriever = QdrantKnowledgeRetriever(collection_name="test_pipeline_kb")
    pipeline.retriever = test_retriever
    indexed_count = pipeline.ingest_file(kb_path)
    assert indexed_count == len(chunks)

    # Verify querying the ingested knowledge
    search_hits = test_retriever.search("كنافة نابلسية بالجبنة السايحة", limit=3)
    assert len(search_hits) > 0
    found_kunafa = any("كنافة" in hit["text"] for hit in search_hits)
    assert found_kunafa

