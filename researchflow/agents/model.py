import json

from langchain_openai import ChatOpenAI

from researchflow.storage import json_text


class Model:
    def __init__(self, settings):
        self.name = settings.base_url + "|" + settings.model
        self.client = ChatOpenAI(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=120,
            max_retries=2,
            temperature=0,
        )

    async def ask(self, role, instruction, data, schema):
        prompt = f"你是论文调研系统的{role}。{instruction}\n只输出符合以下 JSON Schema 的 JSON 对象，不要代码围栏。\n{json_text(schema.model_json_schema())}"
        inputs = json_text(data)
        messages = [("system", prompt), ("human", inputs)]
        for attempt in range(3):
            result = await self.client.ainvoke(messages)
            try:
                content = result.content
                if not isinstance(content, str):
                    raise ValueError("模型未返回文本")
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                parsed = schema.model_validate(json.loads(content))
                return parsed
            except (ValueError, TypeError):
                if attempt == 2:
                    raise ValueError(f"{role}连续返回无效结构化结果") from None
                messages.extend(
                    [
                        ("assistant", str(result.content)),
                        ("human", "返回格式不符合 schema，请修正，输出纯 JSON。"),
                    ]
                )
