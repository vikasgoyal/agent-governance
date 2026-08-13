# Runtime Governance Samples

Small Python examples of runtime controls for AI agents using:

- [Microsoft Agent Governance Toolkit (AGT)](https://github.com/microsoft/agent-governance-toolkit)
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- Azure OpenAI
- YAML-based governance configuration

The workspace currently targets **Python 3.13** and
**`agent-governance-toolkit-core` 4.1.0**.

> These samples demonstrate governance concepts. Pattern-based safety, PII,
> and prompt-injection checks are not comprehensive production defenses.
> Review and extend every policy for your threat model and compliance needs.

## Controls

| # | Control | Sample |
|---|---|---|
| 1 | Tool-call rate limiting | `top10/01_tool_call_rate_limiting.py` |
| 2 | Maximum execution duration and KillSwitch | `top10/02_maximum_agent_duration_ttl.py` |
| 3 | Autonomous action budget | `top10/03_autonomous_action_budget.py` |
| 4 | AI-generated content safety | `top10/_____04_ai_generated_content_safety_check.py` |
| 5 | Prompt-injection detection | `top10/05_prompt_injection_detection.py` |
| 6 | Data sensitivity and PII egress | `top10/06_data_sensitivity_pii_policy.py` |
| 7 | Tool permission boundaries | `top10/_____07_tool_permission_boundary_checks.py` |
| 8 | Repetition and infinite-loop detection | `top10/_____08_repetition_infinite_loop_detection.py` |
| 9 | External communication policy | `top10/_____09_external_communication_policy.py` |
| 10 | Cost and resource guardrails | `top10/10_cost_resource_guardrails.py` |

YAML policies are stored in `top10/policies/`.

## Prerequisites

- Windows with PowerShell
- Python 3.13
- An Azure OpenAI resource and model deployment for samples that use a model
- An identity accepted by `DefaultAzureCredential`

## Set up the environment

From the workspace root:

```powershell
py -3.13 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install `
  "agent-governance-toolkit-core==4.1.0" `
  "agent-framework-core==1.3.0" `
  "agent-framework-openai==1.3.0" `
  azure-identity `
  pyyaml
```

The checked-in workspace configuration selects:

```text
.venv\Scripts\python.exe
```

If PowerShell activation is disabled, run commands with the interpreter
directly:

```powershell
.\.venv\Scripts\python.exe --version
```

## Configure Azure OpenAI

Create a local `.env` file in the workspace root:

```dotenv
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com
AZURE_OPENAI_DEPLOYMENT_NAME=YOUR-DEPLOYMENT
```

The `.env` file is ignored by Git. Do not commit credentials or secrets.

The Azure-backed samples use `DefaultAzureCredential`. Authenticate through a
supported developer credential, such as Azure CLI:

```powershell
az login
```

## Run samples

Activate the environment, then run a sample from the workspace root:

```powershell
python .\top10\01_tool_call_rate_limiting.py
python .\top10\02_maximum_agent_duration_ttl.py
python .\top10\03_autonomous_action_budget.py
python .\top10\05_prompt_injection_detection.py
python .\top10\06_data_sensitivity_pii_policy.py
```

Sample 6 is local and does not call Azure OpenAI:

```powershell
python .\top10\06_data_sensitivity_pii_policy.py
```

Expected behavior:

1. The original payload is classified as sensitive and denied.
2. PII and credentials are redacted.
3. The sanitized payload is classified as public and allowed.

## Verify installed versions

```powershell
python -c "import importlib.metadata as m; print(m.version('agent-governance-toolkit-core'))"
python -m pip check
```

Expected AGT version:

```text
4.1.0
```

## Workspace layout

```text
runtime-governance/
|-- .env                              # local configuration; ignored
|-- .venv/                            # local Python environment; ignored
|-- README.md
|-- runtime-governance.code-workspace
|-- top10/
|   |-- policies/
|   |   |-- 01.yaml
|   |   |-- ...
|   |   `-- 06.yaml
|   |-- 01_tool_call_rate_limiting.py
|   |-- ...
|   `-- 10_cost_resource_guardrails.py
`-- 101/                              # .NET governance example
```

## Security guidance

- Keep `.env` and credentials out of source control.
- Treat regex and built-in pattern detectors as one defense layer, not a
  complete security boundary.
- Enforce controls before model calls, tool execution, external egress,
  logging, memory writes, and audit persistence.
- Use managed identity and least-privilege Azure roles in deployed
  environments.
- Persist governance decisions and termination events to an appropriate audit
  system for production use.
