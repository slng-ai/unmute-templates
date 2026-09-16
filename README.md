# Unmute templates

Ready-made voice agents for [Unmute](https://github.com/slng-ai/unmute).

Each folder is one full agent. You can read it, run it, or copy it and make it
your own. Every folder picks one idea and shows it clearly, so you can start
from the one closest to what you need.

New to Unmute? Read [the docs](https://unmute.ai) first.

## Install

```sh
brew install slng-ai/tap/unmute              # macOS
go install github.com/slng-ai/unmute@latest  # anywhere with Go 1.26+
```

To talk to an agent in your browser you also need one of these:

- [uv](https://docs.astral.sh/uv/) for the Pipecat target
- Docker with Compose for the LiveKit target

## Try one

```sh
git clone https://github.com/slng-ai/unmute-templates
cd unmute-templates

unmute validate single-prompt   # check the files
unmute compile single-prompt    # write the Pipecat and LiveKit projects
unmute dev single-prompt --target pipecat   # talk to it in your browser
```

Put your API keys in a `.env` file. You can put it in the repo root, or inside
the folder of the agent you are running. The table below says which keys each
one needs.

## The templates

| Folder | What it shows | Keys it needs |
|---|---|---|
| [`nemotron-voice-agent`](nemotron-voice-agent/) | NVIDIA's Nemotron blueprint as one Unmute file. Point it at any NIM endpoint — the cloud, your workstation, or a Jetson — by changing one environment variable. | `NVIDIA_API_KEY`, `NVIDIA_NIM_BASE_URL`, `SLNG_API_KEY` |
| [`single-prompt`](single-prompt/) | The simple way: one agent, one prompt, every tool available on every turn. A salon booking line. Start here to see the plain shape before you add structure. | `OPENAI_API_KEY`, `SLNG_API_KEY`, `LANGFUSE_*` |
| [`tasks`](tasks/) | How to collect information step by step. The agent asks for a phone number, name, email and reason for the call, saves each one under a name, and passes them to a tool. The model cannot retype a value it already has. | `OPENAI_API_KEY`, `SLNG_API_KEY`, `LANGFUSE_*` |
| [`multi-agent-handoff`](multi-agent-handoff/) | The full build. Two agents that pass the call to each other, four tasks, PDF documents the agent can search, traces, and a real phone number. The same salon as `single-prompt`, done properly. | `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `SLNG_API_KEY`, `LANGFUSE_*`, Twilio + SIP |
| [`debt-collection`](debt-collection/) | A collections line: payment reminders, arrangements and disputes. Read it for the hard case, an agent that must prove who it is talking to before it says anything at all. Three tools instead of eleven, each with an `action` argument. | `GOOGLE_API_KEY`, `SLNG_API_KEY` |
| [`slng-target`](slng-target/) | Running on SLNG instead of your own machine. A hotel concierge that uses hosted tools, an MCP server, and template variables, so one package can serve many hotels. | `SLNG_API_KEY` |
| [`speech-to-speech-live`](speech-to-speech-live/) | Speech to speech with a live model. One model hears the caller and talks back in its own voice, while a second model runs the tools in the background. A takeaway order line. | `OPENAI_API_KEY` |
| [`speech-to-speech-realtime`](speech-to-speech-realtime/) | Speech to speech with a realtime model doing everything itself. Shows `turn_detection`: who decides the caller has stopped talking. A pharmacy refill line. | `OPENAI_API_KEY` |

`LANGFUSE_*` means all three: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_BASE_URL`. You only need them if you want traces. Remove the
`tracing:` block from `agent.yaml` if you do not.

## What is inside a folder

```
agent.yaml       the agent: models, prompt file, greeting, tools
targets.yaml     which frameworks to build for, and their settings
instructions.md  the prompt
tools/           one file per tool the agent can call
tasks/           steps the agent works through, when it has them
knowledge/       documents the agent can search, when it has them
connections/     phone routes, when it has them
```

## Copy one

```sh
cp -r single-prompt my-agent
```

Then open `my-agent/agent.yaml` and change the `name:` line. Unmute names the
deployment after it, so two agents with the same name will overwrite each
other.

## Help

- Docs: [unmute.ai](https://unmute.ai)
- Issues and questions: [github.com/slng-ai/unmute/issues](https://github.com/slng-ai/unmute/issues)
