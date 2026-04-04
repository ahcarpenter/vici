---
created: 2026-04-04T14:46:15.921Z
title: Add job matching for work requesters via Pinecone semantic search
area: api
files: []
---

## Problem

Work requesters currently have no way to discover available jobs that match the type of work they need. They post a message describing what they need done, but there's no mechanism to surface existing job postings that align with their request.

## Solution

When a work requester submits their original message, use it as a semantic query against the Pinecone vector index of available jobs. Embed the requester's message and perform a similarity search to return the top 10 closest job matches by type of work. Surface these results to the requester so they can see relevant available work before or after posting their request.
