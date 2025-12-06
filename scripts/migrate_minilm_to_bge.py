#!/usr/bin/env python3
"""
Migrate MiniLM Qdrant Collection to BGE Collection

This script:
1. Extracts all unique document file paths from the existing MiniLM collection
2. Reads the original source documents
3. Re-embeds them using BGE-M3 (1024-dim) via the inference service
4. Creates a new Qdrant collection with BGE embeddings
5. Preserves all metadata from the original collection

Usage:
    python scripts/migrate_minilm_to_bge.py [--batch-size 50] [--dry-run]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Set
import time

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from tqdm import tqdm

# Configuration
# Use localhost even if .env says "qdrant" (for Docker internal networking)
# The script runs outside Docker, so needs localhost
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
SOURCE_COLLECTION = "assessment_docs_minilm"
TARGET_COLLECTION = "assessment_docs_bge"
INFERENCE_URL = "http://localhost:8001"
DATA_DIR = Path(__file__).parent.parent / "data"

# BGE-M3 produces 1024-dimensional embeddings
BGE_VECTOR_SIZE = 1024


def get_qdrant_client():
    """Initialize Qdrant client."""
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def get_all_file_paths(client: QdrantClient) -> List[Dict]:
    """
    Extract all unique file paths and their metadata from MiniLM collection.

    Returns:
        List of dicts containing file_path and sample metadata
    """
    print(f"📊 Extracting file paths from {SOURCE_COLLECTION}...")

    file_path_map = {}  # file_path -> {metadata, chunks}
    offset = None
    batch_size = 100
    total_points = 0

    with tqdm(desc="Scanning collection", unit=" points") as pbar:
        while True:
            # Scroll through collection
            result = client.scroll(
                collection_name=SOURCE_COLLECTION,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )

            points, offset = result

            if not points:
                break

            for point in points:
                payload = point.payload
                file_path = payload.get("file_path") or payload.get("source")

                if file_path:
                    if file_path not in file_path_map:
                        file_path_map[file_path] = {
                            "file_path": file_path,
                            "metadata": payload,
                            "chunks": []
                        }

                    # Store chunk info
                    file_path_map[file_path]["chunks"].append({
                        "text": payload.get("text", ""),
                        "chunk_id": payload.get("chunk_id"),
                        "point_id": point.id
                    })

            total_points += len(points)
            pbar.update(len(points))

            if offset is None:
                break

    print(f"✅ Found {total_points} total points across {len(file_path_map)} unique files")
    return list(file_path_map.values())


def read_document_content(file_path: str) -> str:
    """
    Read the original document content from the data directory.

    Args:
        file_path: Relative path to the document

    Returns:
        Document content as string
    """
    # Try multiple possible locations
    possible_paths = [
        DATA_DIR / file_path,
        DATA_DIR / "processed" / file_path,
        DATA_DIR / "raw" / file_path,
        Path(file_path)  # Absolute path
    ]

    for path in possible_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

    # If file not found, reconstruct from chunks
    return None


def embed_text_with_bge(text: str) -> List[float]:
    """
    Embed text using BGE-M3 via inference service.

    Args:
        text: Text to embed

    Returns:
        1024-dimensional embedding vector
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{INFERENCE_URL}/embed",
                json={"texts": [text], "normalize": True}
            )
            response.raise_for_status()
            result = response.json()
            # Return first embedding from the batch
            return result["embeddings"][0]
    except Exception as e:
        print(f"❌ Error embedding text: {e}")
        raise


def create_bge_collection(client: QdrantClient, recreate: bool = False):
    """Create BGE collection with 1024-dimensional vectors."""

    # Check if collection exists
    collections = [c.name for c in client.get_collections().collections]

    if TARGET_COLLECTION in collections:
        if recreate:
            print(f"🗑️  Deleting existing collection {TARGET_COLLECTION}...")
            client.delete_collection(TARGET_COLLECTION)
        else:
            print(f"⚠️  Collection {TARGET_COLLECTION} already exists. Use --recreate to overwrite.")
            return False

    print(f"🆕 Creating collection {TARGET_COLLECTION} with {BGE_VECTOR_SIZE}-dimensional vectors...")
    client.create_collection(
        collection_name=TARGET_COLLECTION,
        vectors_config=VectorParams(
            size=BGE_VECTOR_SIZE,
            distance=Distance.COSINE
        )
    )
    print(f"✅ Collection {TARGET_COLLECTION} created successfully")
    return True


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """
    Split text into chunks for embedding.

    Args:
        text: Text to chunk
        chunk_size: Target chunk size in characters
        chunk_overlap: Overlap between chunks

    Returns:
        List of text chunks
    """
    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at sentence boundary
        if end < text_len:
            last_period = chunk.rfind(".")
            last_newline = chunk.rfind("\n")
            break_point = max(last_period, last_newline)

            if break_point > chunk_size * 0.5:  # At least 50% of chunk
                end = start + break_point + 1
                chunk = text[start:end]

        chunks.append(chunk.strip())
        start = end - chunk_overlap

    return [c for c in chunks if c]  # Filter empty chunks


def migrate_documents(
    client: QdrantClient,
    file_infos: List[Dict],
    batch_size: int = 50,
    dry_run: bool = False
):
    """
    Migrate documents from MiniLM to BGE collection.

    Args:
        client: Qdrant client
        file_infos: List of file info dicts from get_all_file_paths()
        batch_size: Number of points to upload at once
        dry_run: If True, don't actually upload to Qdrant
    """
    print(f"\n🔄 Migrating {len(file_infos)} documents to BGE collection...")

    total_chunks = 0
    points_batch = []
    point_id = 0

    with tqdm(total=len(file_infos), desc="Processing files", unit=" files") as file_pbar:
        for file_info in file_infos:
            file_path = file_info["file_path"]
            original_metadata = file_info["metadata"]
            original_chunks = file_info["chunks"]

            # Try to read original document
            content = read_document_content(file_path)

            # If we can't read the original file, use the existing chunks
            if content is None:
                print(f"⚠️  Could not read {file_path}, using existing chunks")
                chunks = [c["text"] for c in original_chunks if c["text"]]
            else:
                # Re-chunk the document
                chunks = chunk_text(content, chunk_size=500, chunk_overlap=50)

            # Embed each chunk with BGE
            for chunk_idx, chunk_text in enumerate(chunks):
                if not chunk_text.strip():
                    continue

                try:
                    # Get BGE embedding
                    embedding = embed_text_with_bge(chunk_text)

                    # Prepare payload with original metadata + chunk info
                    payload = {
                        **original_metadata,
                        "text": chunk_text,
                        "chunk_id": chunk_idx,
                        "file_path": file_path,
                        "embedding_model": "bge-m3-int8",
                        "vector_size": BGE_VECTOR_SIZE
                    }

                    # Create point
                    point = PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload=payload
                    )
                    points_batch.append(point)
                    point_id += 1
                    total_chunks += 1

                    # Upload batch when full
                    if len(points_batch) >= batch_size:
                        if not dry_run:
                            client.upsert(
                                collection_name=TARGET_COLLECTION,
                                points=points_batch
                            )
                        points_batch = []

                    # Small delay to avoid overloading inference service
                    time.sleep(0.05)

                except Exception as e:
                    print(f"\n❌ Error processing chunk {chunk_idx} of {file_path}: {e}")
                    continue

            file_pbar.update(1)

    # Upload remaining points
    if points_batch and not dry_run:
        client.upsert(
            collection_name=TARGET_COLLECTION,
            points=points_batch
        )

    print(f"\n✅ Migration complete! Processed {total_chunks} chunks from {len(file_infos)} files")

    if dry_run:
        print("🔍 DRY RUN - No data was actually uploaded to Qdrant")


def verify_migration(client: QdrantClient):
    """Verify the migrated collection."""
    print(f"\n🔍 Verifying {TARGET_COLLECTION}...")

    collection_info = client.get_collection(TARGET_COLLECTION)
    print(f"✅ Collection info:")
    print(f"   - Points count: {collection_info.points_count}")
    print(f"   - Vector size: {collection_info.config.params.vectors.size}")
    print(f"   - Distance: {collection_info.config.params.vectors.distance}")

    # Sample a few points
    sample = client.scroll(
        collection_name=TARGET_COLLECTION,
        limit=3,
        with_payload=True,
        with_vectors=False
    )

    print(f"\n📝 Sample points:")
    for point in sample[0]:
        payload = point.payload
        print(f"   - ID: {point.id}")
        print(f"     File: {payload.get('file_path', 'N/A')}")
        print(f"     Chunk: {payload.get('chunk_id', 'N/A')}")
        print(f"     Text preview: {payload.get('text', '')[:100]}...")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate MiniLM Qdrant collection to BGE collection"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of points to upload per batch (default: 50)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without actually uploading to Qdrant"
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate target collection if it exists"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of files to process (for testing)"
    )

    args = parser.parse_args()

    print("🚀 BGE Migration Script")
    print("=" * 60)
    print(f"Source collection: {SOURCE_COLLECTION}")
    print(f"Target collection: {TARGET_COLLECTION}")
    print(f"Inference service: {INFERENCE_URL}")
    print(f"Batch size: {args.batch_size}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    try:
        # Initialize Qdrant client
        client = get_qdrant_client()

        # Test inference service
        print("\n🔍 Testing BGE inference service...")
        test_embedding = embed_text_with_bge("Test query")
        print(f"✅ Inference service OK (embedding dim: {len(test_embedding)})")

        if len(test_embedding) != BGE_VECTOR_SIZE:
            print(f"❌ ERROR: Expected {BGE_VECTOR_SIZE}-dim embeddings, got {len(test_embedding)}")
            return 1

        # Extract file paths from MiniLM collection
        file_infos = get_all_file_paths(client)

        if args.limit:
            print(f"⚠️  Limiting to {args.limit} files for testing")
            file_infos = file_infos[:args.limit]

        # Create BGE collection
        if not args.dry_run:
            created = create_bge_collection(client, recreate=args.recreate)
            if not created and not args.recreate:
                print("\n💡 Use --recreate to overwrite existing collection")
                return 1
        else:
            print("🔍 DRY RUN - Skipping collection creation")

        # Migrate documents
        migrate_documents(
            client,
            file_infos,
            batch_size=args.batch_size,
            dry_run=args.dry_run
        )

        # Verify migration
        if not args.dry_run:
            verify_migration(client)

        print("\n🎉 Migration completed successfully!")
        print("\n📝 Next steps:")
        print("   1. Update .env: QDRANT_COLLECTION=assessment_docs_bge")
        print("   2. Update .env: RAG_VECTOR_SIZE=1024")
        print("   3. Restart backend: docker-compose restart backend")

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️  Migration interrupted by user")
        return 130
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
