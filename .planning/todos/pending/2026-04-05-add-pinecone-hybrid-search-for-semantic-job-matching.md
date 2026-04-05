---
created: 2026-04-05T09:32:00.000Z
title: Add Pinecone hybrid search for semantic job matching
area: api
files:
  - src/matches/service.py
  - src/extraction/pinecone_client.py
  - src/extraction/schemas.py
---

## Problem

Current job matching uses pure earnings-math (rate x duration >= target goal via DP knapsack). This finds jobs that meet the financial goal but ignores the worker's qualitative preferences — e.g., "outdoor jobs only", "near the beach", "good weather expected", or other semantic criteria expressed in natural language alongside their earnings goal.

Workers should be able to express both a financial target AND contextual preferences in a single text message, and the matching pipeline should honor both.

## Solution

Revise the matching pipeline to use **Pinecone hybrid search** (sparse + dense vectors) instead of pure DP-only matching:

1. **Keep discrete field extraction as-is** — GPT still extracts structured fields (pay_rate, duration, location, etc.) for deterministic earnings math
2. **Add semantic filtering via Pinecone** — When finding matches, also filter by nearest-meaning using the job embedding vectors already stored in Pinecone. Worker goal text gets embedded and used as a query vector to find semantically relevant jobs (outdoor, beach, weather, etc.)
3. **Hybrid approach** — Combine the earnings-math DP results with Pinecone semantic similarity scores. Jobs must satisfy the financial threshold AND rank high on semantic relevance to the worker's expressed preferences
4. **Pinecone hybrid search** — Use sparse (keyword/BM25) + dense (embedding) vectors for best-of-both-worlds retrieval

This preserves the deterministic financial matching while adding a semantic layer for qualitative job filtering.
