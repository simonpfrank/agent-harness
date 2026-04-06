# Test Summary

## Unit Tests (70 tests)

### test_types.py (10 tests)
- ToolCall construction with id, name, arguments
- ToolResult success path (output set, error None)
- ToolResult error path (error set, output None)
- Message as user role with defaults
- Message as assistant with tool_calls
- Message as tool with tool_result
- Usage construction with token counts
- Response construction with message, usage, stop_reason
- AgentConfig defaults (tools=[], loop=react, max_turns=10, etc.)
- Callback type aliases are importable

### test_tools.py (14 tests)
- generate_schema produces correct JSON Schema from typed function
- generate_schema handles function with no parameters
- Built-in tools registered (run_command, read_file, execute_code)
- execute_tool returns ToolResult on success
- execute_tool returns error for unknown tool
- execute_tool catches exceptions and returns error
- run_command executes simple command
- run_command respects working_dir
- run_command returns stderr for failing command
- read_file reads file contents
- read_file raises FileNotFoundError for missing file
- execute_code runs Python snippet
- execute_code runs bash snippet
- execute_code captures stderr

### test_budget.py (5 tests)
- Budget with no cost limit never reports exceeded
- Budget tracks turns and reports exceeded at max_turns
- Budget tracks cost and reports exceeded at max_cost
- Budget accumulates cost across multiple calls
- Budget summary returns human-readable string

### test_display.py (7 tests)
- show_response no crash on valid response
- show_response no crash on None content
- show_tool_call no crash on valid tool call
- show_tool_result no crash on success result
- show_tool_result no crash on error result
- show_budget no crash on valid summary string
- prompt_user returns user input

### test_provider_anthropic.py (8 tests)
- User message translates to Anthropic format
- System message extracted from message list
- Assistant message with tool_calls translates correctly
- Tool result message translates to user role with tool_result content
- Tool schema conversion preserves structure
- Text response translates to Response with content
- Tool use response translates with ToolCall list
- chat() calls Anthropic API (mocked client)

### test_config.py (12 tests)
- Loads agent name from config.yaml
- Loads provider and model
- Loads instructions.md content
- Loads optional tools.md as tools_guidance
- Loads tools list from config
- Loads budget settings (max_turns, max_cost)
- Sets agent_dir on config
- Raises FileNotFoundError for missing instructions.md
- Raises ValueError for unknown provider
- Raises ValueError for unknown tool name
- Raises ValueError for max_turns < 1
- Raises FileNotFoundError for nonexistent directory

### test_react_loop.py (6 tests)
- Returns content on end_turn stop reason
- Passes messages and tools to chat function
- Executes tool calls and continues loop
- Stops at max_turns limit
- Calls on_response callback
- Stops when on_budget returns True

### test_cli.py (8 tests)
- Parses run command with agent_dir and prompt
- Parses run command without prompt
- Parses --verbose flag
- Requires agent_dir argument
- Single command mode loads config and runs loop
- Invalid agent dir exits with error
- REPL mode exits on "exit" input
- REPL mode handles KeyboardInterrupt gracefully

## Integration Tests (10 tests)

### test_end_to_end.py
- Loads agents/hello config correctly
- Generates tool schemas for configured tools
- Executes read_file tool on real file
- Tool error (missing file) returns error, doesn't crash
- Missing instructions.md raises FileNotFoundError
- Bad provider raises ValueError
- (API) Single turn simple question returns correct answer
- (API) LLM uses run_command tool to list files
- (API) LLM uses read_file tool and reports contents
- (API) Budget tracks real token usage across turns
