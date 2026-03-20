# Creating and Using Agents in TuskerSquad

This guide explains how to create, register, and use agents in TuskerSquad.

Agents are the core building blocks of the system. Each agent represents a specific engineering role and performs a focused task during the Pull Request workflow.

---

# What is an Agent

An agent is a Python class that:

• receives the current workflow state  
• performs a specific task  
• updates the state with results  
• passes control to the next agent  

Agents collaborate through a shared state managed by the workflow engine.

---

# Types of Agents

TuskerSquad uses two types of agents.

## Deterministic Agents

These agents perform real system operations.

Examples

• building containers  
• running tests  
• calling APIs  
• collecting logs  

They do not use LLMs.

---

## LLM Based Agents

These agents use language models through Ollama.

Examples

• code analysis  
• reasoning  
• summarization  
• decision making  

---

# Agent Structure

All agents follow a simple structure.

Example

class MyAgent:

    def run(self, state):
        return state

The run method takes the workflow state as input and returns the updated state.

---

# Workflow State

Agents communicate through a shared state object.

Example

state = {
    "workflow_id": "",
    "repo_url": "",
    "workspace": "",
    "deploy_url": "",

    "findings": [],
    "logs": [],
    "metrics": {},

    "agent_reports": {},
    "decision": None
}

Agents should only read and update relevant fields.

---

# Creating a New Agent

Step 1 Create a folder

agents/my_agent/

Step 2 Create the agent file

agents/my_agent/my_agent.py

Step 3 Implement the agent

class MyAgent:

    def run(self, state):

        result = "sample output"

        if "findings" not in state:
            state["findings"] = []

        state["findings"].append(result)

        return state

---

# Optional LLM Usage

If your agent needs reasoning, call Ollama.

Example

response = ollama_client.chat(
    model="qwen2.5:14b",
    messages=[{"role": "user", "content": "Analyze code"}],
    temperature=0.1
)

state["agent_reports"]["my_agent"] = response

---

# Registering the Agent

from agents.my_agent.my_agent import MyAgent

graph.add_node("my_agent", MyAgent())

---

# Connecting the Agent

graph.add_edge("planner", "my_agent")
graph.add_edge("my_agent", "next_agent")

---

# Example Agent

class HealthCheckAgent:

    def run(self, state):

        import httpx

        url = state.get("deploy_url")

        try:
            response = httpx.get(url + "/health", timeout=5)

            state["agent_reports"]["health"] = {
                "status": response.status_code
            }

        except Exception as e:
            state["agent_reports"]["health"] = {
                "error": str(e)
            }

        return state

---

# Best Practices

Keep agents small and focused  
Update only relevant state  
Use real checks before LLM reasoning  
Log outputs clearly  
Handle failures safely  

---

# Summary

Agents are the core execution units in TuskerSquad.

Each agent performs a task, updates shared state, and contributes to the final decision.
 