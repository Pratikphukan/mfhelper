import os
import uuid
import logging
import requests
import json
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

@dataclass
class MockBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)
    thought_signature: str = ""

@dataclass
class MockMessage:
    content: list[MockBlock]
    stop_reason: str = "end_turn"


class Claude:
    def __init__(self, model: str):
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self.is_gemini = "gemini" in model.lower() or self.api_key.startswith("AIzaSy")
        
        # Keep track of mapping: tool_use_id -> tool_name
        self.tool_id_to_name = {}

        if not self.is_gemini:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=self.api_key)

    def add_user_message(self, messages: list, message):
        user_message = {
            "role": "user",
            "content": message.content
            if hasattr(message, "content")
            else message,
        }
        messages.append(user_message)

    def add_assistant_message(self, messages: list, message):
        assistant_message = {
            "role": "assistant",
            "content": message.content
            if hasattr(message, "content")
            else message,
        }
        messages.append(assistant_message)

    def text_from_message(self, message):
        return "\n".join(
            [block.text for block in message.content if block.type == "text"]
        )

    def chat(
        self,
        messages,
        system=None,
        temperature=1.0,
        stop_sequences=[],
        tools=None,
        thinking=False,
        thinking_budget=1024,
    ):
        if self.is_gemini:
            return self._chat_gemini(
                messages=messages,
                system=system,
                temperature=temperature,
                stop_sequences=stop_sequences,
                tools=tools,
            )
        else:
            params = {
                "model": self.model,
                "max_tokens": 8000,
                "messages": messages,
                "temperature": temperature,
                "stop_sequences": stop_sequences,
            }

            if thinking:
                params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }

            if tools:
                params["tools"] = tools

            if system:
                params["system"] = system

            message = self.client.messages.create(**params)
            return message

    def _chat_gemini(
        self,
        messages,
        system=None,
        temperature=1.0,
        stop_sequences=[],
        tools=None,
    ):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        
        contents = []
        for msg in messages:
            role = msg["role"]
            gemini_role = "model" if role == "assistant" else "user"
            content = msg["content"]
            
            parts = []
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        b_type = block.get("type")
                        if b_type == "text":
                            parts.append({"text": block.get("text", "")})
                        elif b_type == "tool_use":
                            fc_part = {
                                "functionCall": {
                                    "name": block.get("name"),
                                    "args": block.get("input", {})
                                }
                            }
                            ts = block.get("thought_signature")
                            if ts:
                                fc_part["thoughtSignature"] = ts
                            parts.append(fc_part)
                            self.tool_id_to_name[block.get("id")] = block.get("name")
                        elif b_type == "tool_result":
                            tool_use_id = block.get("tool_use_id")
                            tool_name = self.tool_id_to_name.get(tool_use_id, "unknown_tool")
                            raw_content = block.get("content", "")
                            try:
                                parsed_content = json.loads(raw_content)
                            except Exception:
                                parsed_content = raw_content
                            
                            parts.append({
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {"result": parsed_content}
                                }
                            })
                    else:
                        b_type = getattr(block, "type", None)
                        if b_type == "text":
                            parts.append({"text": getattr(block, "text", "")})
                        elif b_type == "tool_use":
                            fc_part = {
                                "functionCall": {
                                    "name": getattr(block, "name"),
                                    "args": getattr(block, "input", {})
                                }
                            }
                            ts = getattr(block, "thought_signature", "")
                            if ts:
                                fc_part["thoughtSignature"] = ts
                            parts.append(fc_part)
                            self.tool_id_to_name[getattr(block, "id")] = getattr(block, "name")
            
            contents.append({
                "role": gemini_role,
                "parts": parts
            })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 8000,
            }
        }
        
        if stop_sequences:
            payload["generationConfig"]["stopSequences"] = stop_sequences

        if tools:
            gemini_tools = []
            function_declarations = []
            for t in tools:
                input_schema = t.get("input_schema", {})
                
                def uppercase_types(schema):
                    if not isinstance(schema, dict):
                        return schema
                    res = {}
                    for k, v in schema.items():
                        if k == "type" and isinstance(v, str):
                            res[k] = v.upper()
                        elif isinstance(v, dict):
                            res[k] = uppercase_types(v)
                        elif isinstance(v, list):
                            res[k] = [uppercase_types(item) if isinstance(item, dict) else item for item in v]
                        else:
                            res[k] = v
                    return res

                parameters = uppercase_types(input_schema)
                
                function_declarations.append({
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "parameters": parameters
                })
            gemini_tools.append({"function_declarations": function_declarations})
            payload["tools"] = gemini_tools

        if system:
            payload["systemInstruction"] = {
                "parts": [{"text": system}]
            }

        headers = {"Content-Type": "application/json"}
        
        # print(f"DEBUG GEMINI REQUEST: {json.dumps(payload, indent=2)}")
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=30)
            res.raise_for_status()
        except requests.exceptions.HTTPError as err:
            print("ERROR DETAILS:", res.text)
            raise err
        res_data = res.json()
        # print(f"DEBUG GEMINI RESPONSE: {json.dumps(res_data, indent=2)}")
        
        candidates = res_data.get("candidates", [])
        if not candidates:
            return MockMessage(content=[MockBlock(type="text", text="Error: No response candidates returned.")])
            
        candidate = candidates[0]
        gemini_content = candidate.get("content", {})
        parts = gemini_content.get("parts", [])
        
        content_blocks = []
        stop_reason = "end_turn"
        
        for p in parts:
            if "text" in p:
                content_blocks.append(MockBlock(type="text", text=p["text"]))
            elif "functionCall" in p or "function_call" in p:
                fc = p.get("functionCall") or p.get("function_call")
                t_id = f"tool_{uuid.uuid4().hex[:8]}"
                self.tool_id_to_name[t_id] = fc["name"]
                
                content_blocks.append(MockBlock(
                    type="tool_use",
                    id=t_id,
                    name=fc["name"],
                    input=fc.get("args", {}),
                    thought_signature=p.get("thoughtSignature") or p.get("thought_signature") or ""
                ))
                stop_reason = "tool_use"
                
        return MockMessage(content=content_blocks, stop_reason=stop_reason)
