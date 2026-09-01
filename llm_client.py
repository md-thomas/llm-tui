from openai import OpenAI
import logging

log = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 8


class LLMClient:

    def __init__(self, config):
        self.client = OpenAI(
            base_url=config.api_base,
            api_key=config.api_key or "not-needed"
        )

        self.model = config.model
        self.temperature = config.temperature
        self.last_usage = None

    def list_models(self):
        return sorted(model.id for model in self.client.models.list())

    def chat(self, history, system_prompt=None, tools=None, tool_executor=None,
             max_tokens=None, min_p=None, top_k=None, timeout=None, stop_event=None):
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.extend(history)

        kwargs = {}

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if timeout is not None:
            kwargs["timeout"] = timeout

        extra_body = {}

        if min_p is not None:
            extra_body["min_p"] = min_p

        if top_k is not None:
            extra_body["top_k"] = top_k

        if extra_body:
            kwargs["extra_body"] = extra_body

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        self.last_usage = None

        for _ in range(MAX_TOOL_ITERATIONS):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                stream=True,
                stream_options={"include_usage": True},
                **kwargs
            )

            assistant_content = ""
            tool_call_accum = {}

            try:
                for chunk in response:
                    if stop_event is not None and stop_event.is_set():
                        return

                    if chunk.usage:
                        self.last_usage = chunk.usage

                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, "reasoning_content", None)

                    if reasoning:
                        yield ("reasoning", reasoning)

                    if delta.content:
                        assistant_content += delta.content
                        yield ("content", delta.content)

                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            entry = tool_call_accum.setdefault(
                                tc_delta.index, {"id": None, "name": None, "arguments": ""}
                            )

                            if tc_delta.id:
                                entry["id"] = tc_delta.id

                            if tc_delta.function:
                                if tc_delta.function.name:
                                    entry["name"] = tc_delta.function.name

                                if tc_delta.function.arguments:
                                    entry["arguments"] += tc_delta.function.arguments
            finally:
                response.close()

            if stop_event is not None and stop_event.is_set():
                return

            if not tool_call_accum or tool_executor is None:
                return

            messages.append({
                "role": "assistant",
                "content": assistant_content or None,
                "tool_calls": [
                    {
                        "id": entry["id"],
                        "type": "function",
                        "function": {"name": entry["name"], "arguments": entry["arguments"]},
                    }
                    for entry in tool_call_accum.values()
                ],
            })

            for entry in tool_call_accum.values():
                if stop_event is not None and stop_event.is_set():
                    return

                result = tool_executor(entry["name"], entry["arguments"])
                yield ("tool_result", entry["name"], entry["arguments"], result)

                messages.append({
                    "role": "tool",
                    "tool_call_id": entry["id"],
                    "content": result,
                })

        yield ("content", "\n\n[Tool call limit reached; stopping.]")