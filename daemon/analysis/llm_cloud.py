from typing import List, Dict, Any, AsyncGenerator, Optional
import httpx
import json
import asyncio
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class CircuitBreakerOpen(Exception):
    pass

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.is_open = False

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.is_open = True

    def record_success(self):
        self.failures = 0
        self.is_open = False

    def can_proceed(self) -> bool:
        if not self.is_open:
            return True
        # Check if enough time passed to try recovery
        if time.time() - self.last_failure_time > self.recovery_timeout:
            # Half-open state: allow one request to test
            return True
        return False

class CloudLLM:
    def __init__(self, api_keys: Dict[str, str]):
        self.api_keys = api_keys
        self.openai_key = api_keys.get("openai")
        self.anthropic_key = api_keys.get("anthropic")
        
        # One circuit breaker per provider
        self.breakers = {
            "openai": CircuitBreaker(),
            "anthropic": CircuitBreaker()
        }

    async def analyze_stream(self, content: str, provider: str = "openai", model: str = None) -> AsyncGenerator[Dict[str, Any], None]:
        if provider == "openai" and self.openai_key:
            async for issue in self._stream_with_retry("openai", content, model):
                yield issue
        elif provider == "anthropic" and self.anthropic_key:
            async for issue in self._stream_with_retry("anthropic", content, model):
                yield issue
        else:
            print(f"WARNING: No API key found for provider {provider}")
            yield {"type": "error", "message": f"No API key for {provider}"}

    async def _stream_with_retry(self, provider: str, content: str, model: str) -> AsyncGenerator[Dict[str, Any], None]:
        breaker = self.breakers.get(provider)
        if breaker and not breaker.can_proceed():
            yield {"type": "error", "message": f"Circuit breaker open for {provider}. Too many recent failures."}
            return

        try:
            # We use a manual retry loop here to support generator yielding
            # tenacity is harder to wrap around async generators without blocking
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if provider == "openai":
                        async for item in self._stream_openai_impl(content, model):
                            yield item
                    elif provider == "anthropic":
                        async for item in self._stream_anthropic_impl(content, model):
                            yield item
                    
                    # If we finish successfully (or process some stream), reset breaker
                    if breaker: breaker.record_success()
                    return

                except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
                    # Retryable errors
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                        # Rate limit
                        retry_after = int(e.response.headers.get("retry-after", 5))
                        print(f"Rate limit hit for {provider}, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                    else:
                        wait = 2 ** attempt
                        print(f"Error {e}, retrying in {wait}s...")
                        await asyncio.sleep(wait)
                    
                except Exception as e:
                    # Non-retryable
                    print(f"Non-retryable error for {provider}: {e}")
                    raise e
            
            # If we exhausted retries
            if breaker: breaker.record_failure()
            yield {"type": "error", "message": f"Analysis failed after {max_retries} retries."}

        except Exception as e:
            if breaker: breaker.record_failure()
            yield {"type": "error", "message": str(e)}

    async def _stream_openai_impl(self, content: str, model: str = None) -> AsyncGenerator[Dict[str, Any], None]:
        prompt = self._get_prompt(content, json_mode=False)
        model = model or "gpt-4-turbo-preview"
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are an expert code reviewer. Return NDJSON objects."},
                        {"role": "user", "content": prompt}
                    ],
                    "stream": True
                }
            ) as response:
                response.raise_for_status()
                buffer = ""
                async for chunk in response.aiter_lines():
                    if not chunk: continue
                    if chunk.strip() == "data: [DONE]": break
                    if chunk.startswith("data: "):
                        try:
                            data = json.loads(chunk[6:])
                            delta = data["choices"][0].get("delta", {}).get("content", "")
                            if delta:
                                buffer += delta
                                while "\n" in buffer:
                                    line, buffer = buffer.split("\n", 1)
                                    issue = self._parse_single_issue(line, "openai")
                                    if issue: yield issue
                        except:
                            pass

    async def _stream_anthropic_impl(self, content: str, model: str = None) -> AsyncGenerator[Dict[str, Any], None]:
        prompt = self._get_prompt(content, json_mode=False)
        model = model or "claude-3-sonnet-20240229"

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True
                }
            ) as response:
                response.raise_for_status()
                buffer = ""
                async for chunk in response.aiter_lines():
                    if not chunk: continue
                    if chunk.startswith("data: "):
                        try:
                            data = json.loads(chunk[6:])
                            if data["type"] == "content_block_delta":
                                delta = data["delta"].get("text", "")
                                buffer += delta
                                while "\n" in buffer:
                                    line, buffer = buffer.split("\n", 1)
                                    issue = self._parse_single_issue(line, "anthropic")
                                    if issue: yield issue
                        except:
                            pass

    def _get_prompt(self, content: str, json_mode: bool) -> str:
        return f"""
        Analyze the following Python code for bugs, security vulnerabilities, and logic errors.
        Code:
        ```python
        {content}
        ```
        Return distinct JSON objects, one per line (NDJSON).
        Issue Format:
        {{ "id": "CLOUD001", "line": <line>, "message": "<msg>", "type": "bug|security|refactor", "severity": "high|medium|low" }}
        """

    def _parse_single_issue(self, line: str, source: str) -> Optional[Dict[str, Any]]:
        try:
            line = line.strip()
            if not line or line.startswith("```"): return None
            issue = json.loads(line)
            if isinstance(issue, dict) and "message" in issue:
                issue["source"] = f"llm_cloud_{source}"
                return issue
        except:
            pass
        return None
