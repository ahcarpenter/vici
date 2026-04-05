---
created: 2026-04-05T09:35:00.000Z
title: Enrich Pinecone embeddings with structured metadata for filtered semantic matching
area: api
files:
  - src/extraction/pinecone_client.py
  - src/matches/service.py
  - src/jobs/models.py
---

## Problem

Job embeddings written to Pinecone currently store only the vector — no structured metadata is attached. This means the matching pipeline cannot filter by discrete fields (location, pay rate, job type, date, duration) at query time. Additionally, the matching process is purely earnings-math (DP knapsack); it ignores qualitative preferences a worker might express like "outdoor jobs", "near the beach", or "good weather expected".

## Solution

1. **Attach structured metadata to Pinecone vectors** — When writing job embeddings, include extracted fields (location, pay_rate, estimated_duration, ideal_datetime, description keywords, job type/category) as Pinecone metadata. This enables server-side metadata filtering during vector queries.

2. **Leverage semantic search in the matching pipeline** — When a worker texts their goal, embed their message and query Pinecone with both the vector (semantic similarity) and metadata filters (location, date range, pay thresholds). This surfaces jobs that are financially viable AND semantically relevant to the worker's qualitative preferences.

3. **Hybrid matching** — Combine the existing DP earnings-math with Pinecone semantic+metadata results. Financial threshold remains the hard constraint; semantic relevance and metadata filters refine the candidate set and influence ranking.
