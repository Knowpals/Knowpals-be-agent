from typing import List, Dict

import openai

from app.config.loader import AppConfig


class LLMModel:
    def __init__(self,config:AppConfig) -> None:
        self.client=openai.OpenAI(
            api_key=config.openai.api_key,
            base_url=config.openai.base_url,
            timeout=config.openai.timeout,
        )
        self.model=config.openai.model

    def think(self,messages:List[Dict],temperature:float=0)->str:
        try:
            response=self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=False,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ 调用LLM API时发生错误: {e}")
            return "error"