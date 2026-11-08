# Tasks: Show the real error when a category file cannot be loaded

- [x] Design approved in chat (Option 2).
- [x] Change `fetch_category_rankings` in `mfhelper/agent_tools.py`.
- [x] Tests in `tests/test_agent_tools.py`: empty list, bad YAML, private-only, private empty, fallback kept, `.private` not listed.
- [x] Run `pytest tests/`.
