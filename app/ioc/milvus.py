from __future__ import annotations

from pymilvus import (
    connections,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    utility
)

from app.config.loader import AppConfig


def new_milvus_collection(cfg: AppConfig, dim: int = 3072) -> Collection:

    connections.connect(
        alias="default",
        host=cfg.milvus.host,
        port=cfg.milvus.port
    )

    collection_name = cfg.milvus.collection or "knowpals_rag"

    # 如果不存在就创建创建
    if not utility.has_collection(collection_name):

        fields = [
            FieldSchema(
                name="id",
                dtype=DataType.VARCHAR,
                is_primary=True,
                max_length=64
            ),
            FieldSchema(
                name="type",
                dtype=DataType.VARCHAR,
                max_length=32
            ),
            FieldSchema(
                name="knowledge_id",
                dtype=DataType.VARCHAR,
                max_length=64
            ),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=2000
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=dim
            ),
            FieldSchema(
                name="metadata",
                dtype=DataType.JSON
            ),
        ]

        schema = CollectionSchema(
            fields=fields,
            description="RAG documents"
        )

        collection = Collection(
            name=collection_name,
            schema=schema
        )

        #创建索引
        index_params = {
            "metric_type": "IP",   # 内积
            "index_type": "HNSW",
            "params": {
                "M": 16,
                "efConstruction": 200
            }
        }

        collection.create_index(
            field_name="embedding",
            index_params=index_params
        )

    else:
        collection = Collection(collection_name)

    #load到内存
    collection.load()

    return collection