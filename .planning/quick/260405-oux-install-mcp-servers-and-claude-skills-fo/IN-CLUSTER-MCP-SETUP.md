# In-Cluster MCP Server Activation

These MCP servers are configured with placeholder values. To activate them,
run the corresponding port-forward commands.

## Grafana MCP

```bash
kubectl port-forward svc/grafana 3000:3000 -n observability
```

- Then set `GRAFANA_API_KEY` to a valid service account token from Grafana UI
- Or create one via CLI:
  ```bash
  kubectl exec -n observability deploy/grafana -- \
    grafana-cli admin create-service-account-token sa-mcp admin
  ```
- Update `~/.claude.json` vici project mcpServers.grafana.env.GRAFANA_API_KEY with the token

## Temporal MCP

```bash
kubectl port-forward svc/temporal-frontend 7233:7233 -n temporal
```

- No additional auth needed for local port-forward
- Temporal UI also available if port-forwarded separately:
  ```bash
  kubectl port-forward svc/temporal-ui 8233:8080 -n temporal
  ```

## OpenTelemetry / Jaeger MCP

```bash
kubectl port-forward svc/jaeger-query 16686:16686 -n observability
kubectl port-forward svc/otel-collector 4318:4318 -n observability
```

- Jaeger query UI also available at http://localhost:16686
- OTEL collector receives traces/metrics at http://localhost:4318

## Cloud API Servers (ready to use)

These work immediately if env vars are set in your shell profile:

| Server | Env Var | How to Get |
|--------|---------|------------|
| Pulumi | `PULUMI_ACCESS_TOKEN` | https://app.pulumi.com/account/tokens |
| GitHub | `GITHUB_PERSONAL_ACCESS_TOKEN` | `gh auth token` or https://github.com/settings/tokens |
| Pinecone | `PINECONE_API_KEY` | https://app.pinecone.io/ console |
| Render | (configured via Bearer token) | Already set in ~/.claude.json |

## Verifying MCP Servers

After starting port-forwards, restart Claude Code to pick up the MCP connections.
Claude will auto-discover servers from `~/.mcp.json` (global) and `~/.claude.json` (project).
