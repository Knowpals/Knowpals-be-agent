import re
from typing import List

class TextChunker:
    def __init__(self,max_size:int=400,overlap:int=50):
        self.max_size = max_size
        self.overlap = overlap

    def chunk(self, text: str, doc_type: str) -> List[str]:
        text = self._clean(text)

        if doc_type == "question":
            return [text]

        elif doc_type == "knowledge":
            return self._chunk_by_paragraph(text)

        elif doc_type == "segment":
            return self._chunk_by_length(text)

        else:
            return self._chunk_by_length(text)

    def _clean(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r"\n+", "\n", text)
        text = text.replace("\t", " ")
        return text


    def _chunk_by_paragraph(self, text: str) -> List[str]:
        paragraphs = text.split("\n")

        chunks = []
        current = ""

        for p in paragraphs:
            if len(current) + len(p) < self.max_size:
                current += p + "\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = p

        if current:
            chunks.append(current.strip())

        return chunks

    def _chunk_by_length(self, text: str) -> List[str]:
        chunks = []

        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + self.max_size
            chunk = text[start:end]

            chunks.append(chunk)

            start = end - self.overlap  # overlap

        return chunks