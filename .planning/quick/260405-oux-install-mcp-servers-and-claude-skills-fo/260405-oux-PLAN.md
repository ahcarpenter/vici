---
phase: quick-260405-oux
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ~/.mcp.json
  - ~/.claude.json
  - .claude/skills/temporal/SKILL.md
  - .claude/skills/temporal/rules/workflows.md
  - .claude/skills/temporal/rules/activities.md
autonomous: true
must_haves:
  truths:
    - "Claude Code can invoke all 8 MCP servers via tool calls"
    - "Temporal skill is available in project .claude/skills/"
    - "Pinecone plugin is installed and configured"
  artifacts:
    - path: "~/.mcp.json"
      provides: "Global MCP servers (GitHub, Kubernetes, Docker)"
    - path: "~/.claude.json"
      provides: "Project MCP servers (Pulumi, Grafana, Temporal, OTEL, Pinecone, Render)"
    - path: ".claude/skills/temporal/SKILL.md"
      provides: "Temporal workflow skill index"
  key_links:
    - from: "~/.mcp.json"
      to: "Claude Code global config"
      via: "MCP server auto-discovery"
    - from: "~/.claude.json"
      to: "Claude Code project config"
      via: "Project-scoped MCP server loading"
---

<objective>
Install 8 MCP servers and 2 Claude skills/plugins for the vici project tech stack.

Purpose: Give Claude Code direct tool access to Pulumi, Grafana, Temporal, OTEL, Kubernetes, GitHub, Pinecone, and Docker -- plus Temporal workflow skill and Pinecone plugin.
Output: Updated ~/.mcp.json (global), ~/.claude.json (project-specific), and .claude/skills/ directory.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Install global and project-scoped MCP servers</name>
  <files>~/.mcp.json, ~/.claude.json</files>
  <action>
Update both MCP config files using JSON manipulation (python3 or jq). Read-modify-write to preserve existing entries.

**~/.mcp.json (global) -- ADD these 3 servers alongside existing gcloud/storage:**

1. **github** (GitHub MCP Server):
```json
"github": {
  "command": "docker",
  "args": ["run", "-i", "--rm",
    "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
    "ghcr.io/github/github-mcp-server"],
  "env": {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"
  }
}
```
Note: Requires GITHUB_PERSONAL_ACCESS_TOKEN in shell env. Check if `gh auth token` works and document.

2. **kubernetes** (Kubernetes MCP Server):
```json
"kubernetes": {
  "command": "npx",
  "args": ["-y", "kubernetes-mcp-server"]
}
```
Uses existing kubeconfig automatically.

3. **docker** (Docker MCP Server):
```json
"docker": {
  "command": "uvx",
  "args": ["mcp-server-docker"]
}
```
Uses Docker socket directly.

**~/.claude.json (project-specific under vici project mcpServers) -- ADD these 5 servers alongside existing render:**

4. **pulumi** (Pulumi MCP Server):
```json
"pulumi": {
  "command": "npx",
  "args": ["-y", "@pulumi/mcp-server@latest"],
  "env": {
    "PULUMI_ACCESS_TOKEN": "${PULUMI_ACCESS_TOKEN}"
  }
}
```
Requires PULUMI_ACCESS_TOKEN in shell env.

5. **grafana** (Grafana MCP -- IN-CLUSTER, placeholder config):
```json
"grafana": {
  "command": "docker",
  "args": ["run", "-i", "--rm",
    "-e", "GRAFANA_URL",
    "-e", "GRAFANA_API_KEY",
    "mcp/grafana"],
  "env": {
    "GRAFANA_URL": "http://localhost:3000",
    "GRAFANA_API_KEY": "PLACEHOLDER_NEEDS_PORT_FORWARD_OR_INGRESS"
  }
}
```
Note: Grafana is in-cluster on GKE. Requires `kubectl port-forward svc/grafana 3000:3000 -n observability` or ingress setup before use.

6. **temporal** (Temporal MCP -- IN-CLUSTER, placeholder config):
```json
"temporal": {
  "command": "docker",
  "args": ["run", "-i", "--rm",
    "-e", "TEMPORAL_ADDRESS",
    "ghcr.io/gethosthewalrus/temporal-mcp:latest"],
  "env": {
    "TEMPORAL_ADDRESS": "localhost:7233"
  }
}
```
Note: Temporal is in-cluster on GKE. Requires `kubectl port-forward svc/temporal-frontend 7233:7233 -n temporal` before use.

7. **opentelemetry** (OTEL MCP -- IN-CLUSTER, placeholder config):
```json
"opentelemetry": {
  "command": "npx",
  "args": ["-y", "@traceloop/mcp-server-otel"],
  "env": {
    "JAEGER_QUERY_URL": "http://localhost:16686",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"
  }
}
```
Note: Jaeger is in-cluster. Requires `kubectl port-forward svc/jaeger-query 16686:16686 -n observability` before use.

8. **pinecone** (Pinecone MCP):
```json
"pinecone": {
  "command": "npx",
  "args": ["-y", "@anthropic/pinecone-mcp"],
  "env": {
    "PINECONE_API_KEY": "${PINECONE_API_KEY}"
  }
}
```
Requires PINECONE_API_KEY in shell env.

**Implementation approach:**
- Use python3 to read, merge, and write JSON for both files
- Preserve all existing keys and formatting
- For ~/.claude.json, navigate to projects["/Users/ahcarpenter/workspace/vici"].mcpServers and merge new servers
- Do NOT overwrite existing entries (render, gcloud, storage)
  </action>
  <verify>
    <automated>python3 -c "
import json
with open('$HOME/.mcp.json') as f: g = json.load(f)
assert 'github' in g['mcpServers'], 'Missing github'
assert 'kubernetes' in g['mcpServers'], 'Missing kubernetes'
assert 'docker' in g['mcpServers'], 'Missing docker'
assert 'gcloud' in g['mcpServers'], 'Existing gcloud lost'
assert 'storage' in g['mcpServers'], 'Existing storage lost'
print('Global MCP: OK -', list(g['mcpServers'].keys()))

with open('$HOME/.claude.json') as f: c = json.load(f)
vici = c['projects']['/Users/ahcarpenter/workspace/vici']['mcpServers']
for s in ['render','pulumi','grafana','temporal','opentelemetry','pinecone']:
    assert s in vici, f'Missing {s}'
print('Project MCP: OK -', list(vici.keys()))
"</automated>
  </verify>
  <done>
    - ~/.mcp.json contains 5 servers: gcloud, storage, github, kubernetes, docker
    - ~/.claude.json vici project contains 6 servers: render, pulumi, grafana, temporal, opentelemetry, pinecone
    - All existing entries preserved
    - In-cluster servers (grafana, temporal, opentelemetry) have placeholder values with port-forward instructions in comments
  </done>
</task>

<task type="auto">
  <name>Task 2: Install Temporal Claude skill and Pinecone plugin</name>
  <files>.claude/skills/temporal/SKILL.md, .claude/skills/temporal/rules/workflows.md, .claude/skills/temporal/rules/activities.md</files>
  <action>
**Temporal Skill (mfateev/temporal-claude-skill):**

Clone or fetch the temporal-claude-skill repo content and install into the project skills directory:

```bash
# Clone to temp location
git clone --depth 1 https://github.com/mfateev/temporal-claude-skill.git /tmp/temporal-claude-skill

# Create project skills directory
mkdir -p .claude/skills/temporal/rules

# Copy skill files into project structure
# Inspect the repo structure first, then map files to SKILL.md + rules/*.md format
```

If the repo has a different structure than expected, adapt:
- Create SKILL.md as an index file (~130 lines max) summarizing what the skill provides
- Place detailed rule files under rules/
- If the repo is just a single markdown or set of instructions, organize into SKILL.md (index) and rules/workflows.md + rules/activities.md (detailed rules)

The SKILL.md should cover:
- Temporal workflow patterns (retry policies, timeouts, signals, queries)
- Activity best practices (idempotency, heartbeats)
- Testing patterns for workflows and activities
- Reference to the vici project's existing temporal code at src/temporal/

**Pinecone Plugin (pinecone-io/pinecone-claude-code-plugin):**

```bash
git clone --depth 1 https://github.com/pinecone-io/pinecone-claude-code-plugin.git /tmp/pinecone-claude-code-plugin
```

Inspect the repo to determine install method:
- If it is a Claude Code plugin: copy to ~/.claude/plugins/ or follow the repo's install instructions
- If it provides skills: install to .claude/skills/pinecone/
- Follow whatever install mechanism the repo documents

Clean up temp directories after install.
  </action>
  <verify>
    <automated>test -f .claude/skills/temporal/SKILL.md && echo "Temporal skill: OK" || echo "FAIL: Temporal skill missing"; ls .claude/skills/temporal/rules/*.md 2>/dev/null | wc -l | xargs -I{} echo "Temporal rules: {} files"</automated>
  </verify>
  <done>
    - .claude/skills/temporal/SKILL.md exists with index of Temporal patterns
    - At least 1 rules file exists under .claude/skills/temporal/rules/
    - Pinecone plugin installed per its repo instructions
    - Temp clone directories cleaned up
  </done>
</task>

<task type="auto">
  <name>Task 3: Create setup documentation for in-cluster MCP servers</name>
  <files>.planning/quick/260405-oux-install-mcp-servers-and-claude-skills-fo/IN-CLUSTER-MCP-SETUP.md</files>
  <action>
Create a quick reference doc listing what port-forwards or env vars are needed to activate the three in-cluster MCP servers. This is NOT a README -- it is an operational reference for the developer.

Content:

```
# In-Cluster MCP Server Activation

These MCP servers are configured with placeholder values. To activate them,
run the corresponding port-forward commands.

## Grafana MCP
kubectl port-forward svc/grafana 3000:3000 -n observability
- Then set GRAFANA_API_KEY to a valid service account token from Grafana UI
- Or create one: kubectl exec -n observability deploy/grafana -- grafana-cli admin create-service-account-token ...

## Temporal MCP
kubectl port-forward svc/temporal-frontend 7233:7233 -n temporal
- No additional auth needed for local port-forward

## OpenTelemetry / Jaeger MCP
kubectl port-forward svc/jaeger-query 16686:16686 -n observability
kubectl port-forward svc/otel-collector 4318:4318 -n observability
- Jaeger query UI also available at localhost:16686

## Cloud API Servers (ready to use)
These work immediately if env vars are set:
- PULUMI_ACCESS_TOKEN (pulumi login token)
- GITHUB_PERSONAL_ACCESS_TOKEN (gh auth token or PAT)
- PINECONE_API_KEY (Pinecone console)
```
  </action>
  <verify>
    <automated>test -f .planning/quick/260405-oux-install-mcp-servers-and-claude-skills-fo/IN-CLUSTER-MCP-SETUP.md && echo "Setup doc: OK" || echo "FAIL"</automated>
  </verify>
  <done>
    - IN-CLUSTER-MCP-SETUP.md exists with port-forward commands for all 3 in-cluster services
    - Cloud API env var requirements documented
  </done>
</task>

</tasks>

<verification>
- All 8 MCP servers configured across global and project configs
- Existing MCP entries (gcloud, storage, render) preserved
- Temporal skill installed to project .claude/skills/
- Pinecone plugin installed per repo instructions
- In-cluster servers have placeholder values with activation instructions
</verification>

<success_criteria>
- `~/.mcp.json` has 5 servers (gcloud, storage, github, kubernetes, docker)
- `~/.claude.json` vici project has 6 servers (render, pulumi, grafana, temporal, opentelemetry, pinecone)
- `.claude/skills/temporal/SKILL.md` exists with Temporal patterns
- IN-CLUSTER-MCP-SETUP.md documents activation steps
- No existing config entries lost or corrupted
</success_criteria>

<output>
After completion, create `.planning/quick/260405-oux-install-mcp-servers-and-claude-skills-fo/260405-oux-SUMMARY.md`
</output>
