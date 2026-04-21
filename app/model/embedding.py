from typing import Any

from openai import OpenAI

from app.config.loader import AppConfig


class EmbeddingModel:
    def __init__(self,config:AppConfig,model="text-embedding-3-large") -> None:
        self.client=OpenAI(
            api_key=config.openai.api_key,
            base_url=config.openai.base_url,
            timeout=config.openai.timeout,
        )
        self.model=model

    def encode(self,text:str) -> Any:
        if not text:
            return None

        resp=self.client.embeddings.create(
            model=self.model,
            input=text,
        )

        return resp.data[0].embedding

    def encode_batch(self, texts: list[str]):
        texts = [t if t else "" for t in texts]

        resp = self.client.embeddings.create(
            model=self.model,
            input=texts
        )

        return [item.embedding for item in resp.data]
