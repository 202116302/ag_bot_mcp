"""Shared Responses-style interface; Mock never represents a real model trial."""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from typing import Protocol

import requests

from .fertilizer import ROOT
from .schemas import Contract
from pydantic import Field
from typing import Literal


class LLMConfig(Contract):
    model: Literal['gpt-5.4-mini', 'gpt-5.4-mini-2026-03-17']
    reasoning_effort: Literal['none', 'low', 'medium', 'high', 'xhigh']
    max_output_tokens: int = Field(ge=256, le=4096)
    max_model_calls: int = Field(ge=1, le=5)
    max_tool_calls: int = Field(ge=1, le=4)


def load_llm_config() -> LLMConfig:
    return LLMConfig.model_validate_json((ROOT / 'configs/llm.json').read_text(encoding='utf-8'))


class ModelError(RuntimeError):
    """Only sanitized error codes, never HTTP request headers or exception URLs."""


def read_openai_key() -> str:
    value = os.getenv('OPENAI_API_KEY', '').strip()
    if not value:
        path = ROOT / '.env'
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                name, sep, candidate = line.strip().partition('=')
                if sep and name.strip() == 'OPENAI_API_KEY':
                    value = candidate.strip().strip('\"\'')
    if not value:
        raise ModelError('OPENAI_API_KEY_MISSING')
    return value


@dataclass
class ModelReply:
    raw: dict

    @property
    def output(self) -> list[dict]:
        return self.raw.get('output', [])

    @property
    def text(self) -> str:
        return ''.join(part.get('text', '') for item in self.output
                       if item.get('type') == 'message'
                       for part in item.get('content', []) if part.get('type') == 'output_text')


class LanguageModel(Protocol):
    provider: str
    model: str

    async def complete(self, *, instructions: str, input: list[dict],
                       tools: list[dict], schema: dict) -> ModelReply: ...


class OpenAIModel:
    provider = 'openai'

    def __init__(self, config: LLMConfig, *, api_key: str | None = None):
        self.config = config
        self.model = config.model
        self._api_key = api_key or read_openai_key()

    async def complete(self, *, instructions, input, tools, schema) -> ModelReply:
        payload = dict(model=self.model, instructions=instructions, input=input,
                       tools=tools, tool_choice='auto', parallel_tool_calls=False,
                       reasoning={'effort': self.config.reasoning_effort},
                       max_output_tokens=self.config.max_output_tokens, store=False,
                       text={'format': {'type': 'json_schema', 'name': 'fertilizer_explanation',
                                        'strict': True, 'schema': schema}})
        return await asyncio.to_thread(self._request, payload)

    def _request(self, payload) -> ModelReply:
        try:
            response = requests.post('https://api.openai.com/v1/responses',
                                     headers={'Authorization': 'Bearer ' + self._api_key},
                                     json=payload, timeout=(8, 45), allow_redirects=False)
        except requests.RequestException:
            raise ModelError('OPENAI_NETWORK_ERROR') from None
        if response.status_code != 200:
            raise ModelError('OPENAI_HTTP_' + str(response.status_code))
        try:
            # API response text is untrusted; redact even if it echoes a key.
            raw = json.loads(response.text.replace(self._api_key, '[REDACTED]'))
        except ValueError:
            raise ModelError('OPENAI_INVALID_RESPONSE') from None
        if not isinstance(raw, dict) or not isinstance(raw.get('output'), list):
            raise ModelError('OPENAI_INVALID_RESPONSE')
        return ModelReply(raw)


class MockModel:
    provider = 'mock'
    model = 'mock-fertilizer-v1'

    async def complete(self, *, instructions, input, tools, schema) -> ModelReply:
        context = json.loads(input[0]['content'])
        outputs = [item for item in input if item.get('type') == 'function_call_output']
        documents = context.get('retrieved_documents', []) if not tools else []
        if not outputs and not documents:
            output = [{'type': 'function_call', 'call_id': 'mock-call-1',
                       'name': 'get_fertilizer_prescription',
                       'arguments': json.dumps({'pnu_code': context['pnu_code'],
                                                'crop_code': context['crop_code']})}]
        else:
            from .explanation import explanation_from_prescription
            from .fertilizer import FertilizerPrescription
            data = (FertilizerPrescription.model_validate(documents[0]['content']) if documents
                    else FertilizerPrescription.model_validate_json(outputs[-1]['output']))
            answer = explanation_from_prescription(data)
            if 'required_notices' in context:
                answer.notices = context['required_notices']
            output = [{'type': 'message', 'role': 'assistant', 'content': [
                {'type': 'output_text', 'text': answer.model_dump_json()}]}]
        return ModelReply({'id': 'mock-response-' + str(len(outputs)), 'status': 'completed',
                           'model': self.model, 'output': deepcopy(output), 'usage': None})
