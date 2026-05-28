# One-pager: Programmatic Agentic-Coding Benchmark

Date: 2026-05-24

## Goal

Measure llama.cpp long-context prefill and generation throughput with a reproducible agentic-coding workload, without relying on an LLM to invent tasks during the benchmark.

The benchmark should produce clean, correlated artifacts:

```text
client request log → proxy access log → llama.cpp backend task/timing log → final report
```

## Core design

Use a deterministic task corpus instead of generated prompts.

Each benchmark item is a static JSON fixture:

```json
{
  "id": "graph_dijkstra_state_001",
  "language": "cpp",
  "category": "graph_shortest_path",
  "difficulty": "leetcode_hard",
  "prompt": "...full problem statement...",
  "requirements": [
    "explain approach",
    "provide code in cpp",
    "analyze complexity",
    "include edge cases"
  ]
}
```

The runner cycles through fixtures by fixed schedule:

```text
Python → C++ → Java → TypeScript → Go → repeat
```

No model-generated problem creation. The model only solves prewritten tasks.

## Workload construction

Build 100-150 static tasks covering distinct categories:

```text
arrays/sliding window
binary search / parametric search
dynamic programming
interval DP
graph shortest path
graph flow / matching
tree DP
segment tree / Fenwick
string automata / KMP / suffix
math / combinatorics
geometry / sweep line
union-find / offline queries
```

For each task, include:

- unique ID
- language
- category
- problem text
- expected code fence language
- optional reference solution metadata, not sent to model

## Runner requirements

The benchmark client must be deterministic and self-validating.

For each iteration:

1. Select next fixture from the schedule.
2. Send prompt with explicit `REQUEST_ID`, `TASK_ID`, `LANGUAGE`, and `ITERATION`.
3. Require output format:

```text
## Approach
## Code
```<language>
...
```
## Complexity
## Tests
## Self-evaluation
```

4. Parse response and validate:
   - required sections present
   - code fence language matches fixture
   - response contains no “I will create a problem” meta-task drift
   - response task ID matches request
   - minimum code length / token count
5. If validation fails, log failure and stop or retry once with same fixture.

## Logging and correlation

Write JSONL for every request:

```json
{
  "event": "request_end",
  "run_id": "...",
  "iteration": 42,
  "request_id": "...",
  "task_id": "graph_flow_007",
  "language": "java",
  "client_start": "...",
  "client_end": "...",
  "http_status": 200,
  "backend_task": 12345,
  "slot_tokens": 98321,
  "prompt_eval_tokens": 3187,
  "prompt_tps": 642.1,
  "eval_tokens": 2048,
  "eval_tps": 91.4,
  "draft_acceptance": 0.82,
  "validation": {"ok": true}
}
```

The backend parser should extract from llama.cpp:

```text
processing task
prompt eval time
eval time
draft acceptance rate
stop processing: n_tokens = ..., truncated = ...
```

The proxy log is only a transport audit: request count, status codes, and timestamps.

## Reporting

Generate the report from JSONL only, with raw log paths listed.

Required sections:

- hardware and runtime config
- run validity summary
- validation failures, if any
- request count and language distribution
- context progression
- prefill TPS by 30k context band
- generation TPS by 30k context band
- draft acceptance by band
- final max context and truncation status

Never include a run in benchmark results unless:

```text
all requests validated
all proxy statuses are 200
backend releases == client completed requests
truncated == 0 unless explicitly testing truncation
language distribution matches schedule
```

## Why this avoids the failure mode

The model no longer controls the benchmark workload. It cannot inflate TPS by repeating its own task-generation scaffold or collapsing into similar prompts. The client enforces task identity, language rotation, output structure, and log correlation before any throughput numbers are trusted.
