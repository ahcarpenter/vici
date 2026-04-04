---
created: 2026-04-04T14:46:15.921Z
title: Add natural language job posting search for work requesters via Pinecone and GPT
area: api
files: []
---

## Problem

Work requesters have no way to ask questions about available job postings using natural language over text. They need a conversational interface to query existing listings (e.g. "are there any plumbing jobs in Brooklyn this week?") without knowing how the data is structured.

## Solution

Build a natural language query flow for work requesters where their text message is embedded and used to perform semantic search against job postings in Pinecone. Combine retrieval results with GPT to generate a natural language answer grounded in the actual job postings. Expose this via the existing messaging interface so requesters can converse about available work over text.
