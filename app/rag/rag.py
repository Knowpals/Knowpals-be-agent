import uuid
from typing import List, Dict

from pymilvus import Collection

from app.model.embedding import EmbeddingModel
from app.rag.chunker import TextChunker


class RagService:
    def __init__(self,collection:Collection,embedding:EmbeddingModel,chunker:TextChunker):
        self.collection = collection
        self.embedding = embedding
        self.chunker = chunker


    def insert_docs(self, docs: List[Dict]):
        ids = [d["id"] for d in docs]
        types = [d["type"] for d in docs]
        knowledge_ids = [d["knowledge_id"] for d in docs]
        contents = [d["content"] for d in docs]
        embeddings = [d["embedding"] for d in docs]
        metadatas = [d["metadata"] for d in docs]

        self.collection.insert([
            ids,
            types,
            knowledge_ids,
            contents,
            embeddings,
            metadatas
        ])

        self.collection.flush()

    #插入单条数据
    def add_doc(self, doc_type, content, knowledge_id, **meta):
        contents = self.chunker.chunk(content, doc_type)

        embeddings = self.embedding.encode_batch(contents)

        docs = []
        for i, c in enumerate(contents):
            docs.append({
                "id": str(uuid.uuid4()),
                "type": doc_type,
                "knowledge_id": knowledge_id,
                "content": c,
                "embedding": embeddings[i],
                "metadata": meta
            })

        self.insert_docs(docs)


    def search(self,
               query:str,
               knowledge_id:str=None,
               doc_type:str=None,
               top_k:int=5,
        ):
        vector = self.embedding.encode(query)
        expr = []
        if knowledge_id:
            expr.append(f'knowledge_id == "{knowledge_id}"')

        if doc_type:
            expr.append(f'type == "{doc_type}"')

        expr = " and ".join(expr) if expr else None

        results = self.collection.search(
            data=[vector],
            anns_field="embedding",
            param={"metric_type": "IP", "params": {"ef": 64}},
            limit=top_k,
            expr=expr,
            output_fields=["type", "knowledge_id", "content", "metadata"]
        )

        return self._format_results(results)

    def _format_results(self, results):
        out = []
        for hits in results:
            for h in hits:
                out.append({
                    "score": h.score,
                    "type": h.entity.get("type"),
                    "knowledge_id": h.entity.get("knowledge_id"),
                    "content": h.entity.get("content"),
                    "metadata": h.entity.get("metadata")
                })
        return out