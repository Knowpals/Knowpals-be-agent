import json
from http import HTTPStatus
from typing import Any
from urllib import request

import dashscope
from dashscope import Transcription

from app.config.loader import AppConfig


class ASRModel:
    def __init__(self,cfg: AppConfig):
        dashscope.base_http_api_url = cfg.dashscope.base_http_api_url
        dashscope.api_key = cfg.dashscope.api_key

    def transcribe(self,payload: dict[str, Any])->dict:
        file_urls = payload.get("file_urls")
        if not file_urls:
            raise ValueError("payload must contain 'file_urls'")

        model = payload.get("model", "fun-asr")
        language_hints = payload.get("language_hints", ["zh"])

        #提交任务
        task_response = Transcription.async_call(
            model=model,
            file_urls=file_urls,
            language_hints=language_hints,
        )

        #等待结果
        transcription_response = Transcription.wait(task=task_response.output.task_id)

        if transcription_response.status_code != HTTPStatus.OK:
            message = getattr(
                transcription_response.output, "message", transcription_response.output
            )
            raise RuntimeError(f"Transcription API error: {message}")

        final_text = []
        sentences = []
        max_end = 0

        for item in transcription_response.output["results"]:
            if item["subtask_status"] == "SUCCEEDED":
                url = item["transcription_url"]
                body = json.loads(request.urlopen(url).read().decode("utf-8"))

                #fun-asr结构解析：只要sentences
                for trans in body.get("transcripts", []):
                    final_text.append(trans.get("text", ""))

                    for s in trans.get("sentences", []):
                        sentence = {
                            "text": s.get("text", ""),
                            "start_ms": s.get("begin_time", 0),
                            "end_ms": s.get("end_time", 0),
                        }
                        sentences.append(sentence)
                        max_end = max(max_end, sentence["end_ms"])
            else:
                raise RuntimeError(f"transcription failed: {item}")

        return {
            "text": "".join(final_text),
            "sentences": sentences,
            "duration_ms": max_end,
        }
