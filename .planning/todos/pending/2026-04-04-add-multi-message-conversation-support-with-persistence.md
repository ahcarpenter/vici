---
created: 2026-04-04T14:46:15.921Z
title: Add multi-message conversation support with persistence
area: api
files: []
---

## Problem

The current messaging flow treats each inbound message as a standalone interaction. There is no concept of a running conversation thread, so context from prior messages is lost between turns. This prevents natural back-and-forth exchanges (e.g. follow-up questions, clarifications, multi-step flows).

## Solution

Persist conversation history per user session (likely keyed by phone number or session ID). Store message turns (role + content) in the database. When processing a new inbound message, load the prior conversation history and pass it as context to the LLM so it can respond coherently across multiple turns. Define a strategy for conversation expiry or reset (e.g. timeout-based or explicit user command).
