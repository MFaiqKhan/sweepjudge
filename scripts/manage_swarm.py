"""
Command-line interface for dynamically managing the agent swarm.

This script communicates with the orchestrator's API to add, remove,
and list running agents.

Examples:
  python scripts/manage_swarm.py add --agent-class FetcherAgent --count 3
  python scripts/manage_swarm.py list
  python scripts/manage_swarm.py remove fetcher-1
"""
import typer
import httpx
import json

app = typer.Typer(help="A CLI to manage the agent swarm via the orchestrator API.")
ORCHESTRATOR_URL = "http://localhost:8000"

@app.command()
def add(
    agent_class: str = typer.Option(..., "--agent-class", help="Class name of the agent, e.g., FetcherAgent"),
    count: int = typer.Option(1, "--count", help="Number of instances to create"),
    base_id: str = typer.Option(None, "--base-id", help="Base ID for agents, e.g., fetcher -> fetcher-1"),
    config: str = typer.Option(None, "--config", "-c", help="JSON configuration string for the agents."),
):
    """Add one or more agents with the same configuration to the swarm."""
    if not base_id:
        base_id = agent_class.replace("Agent", "").lower()

    print(f"Adding {count} instance(s) of {agent_class} with base ID '{base_id}'...")
    
    config_data = None
    if config:
        try:
            config_data = json.loads(config)
            print(f"Using configuration: {json.dumps(config_data, indent=2)}")
        except json.JSONDecodeError:
            print("❌ Error: Invalid JSON provided for --config.")
            raise typer.Exit(1)
            
    for i in range(1, count + 1):
        agent_id = f"{base_id}-{i}"
        print(f"  -> Requesting to add agent '{agent_id}'...")
        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{ORCHESTRATOR_URL}/agents/add",
                    json={"agent_class_name": agent_class, "agent_id": agent_id, "config": config_data},
                    timeout=10,
                )
            response.raise_for_status()
            print(f"     ✅ Success: {response.status_code} {response.json().get('message')}")
        except httpx.HTTPStatusError as e:
            print(f"     ❌ Error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError:
            print(f"     ❌ Request failed: Could not connect to orchestrator at {ORCHESTRATOR_URL}. Is it running?")


@app.command()
def remove(agent_id: str = typer.Argument(..., help="The full ID of the agent to remove, e.g., fetcher-1")):
    """Stop and remove a specific agent from the swarm."""
    print(f"Requesting to remove agent '{agent_id}'...")
    try:
        with httpx.Client() as client:
            response = client.delete(f"{ORCHESTRATOR_URL}/agents/remove/{agent_id}")
        response.raise_for_status()
        print(f"  ✅ Success: {response.status_code} {response.json().get('message')}")
    except httpx.HTTPStatusError as e:
        print(f"  ❌ Error: {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        print(f"  ❌ Request failed: Could not connect to orchestrator at {ORCHESTRATOR_URL}.")

@app.command(name="list")
def list_agents():
    """List all active agents in the swarm."""
    print("Fetching active agents...")
    try:
        with httpx.Client() as client:
            response = client.get(f"{ORCHESTRATOR_URL}/agents/")
        response.raise_for_status()
        
        data = response.json()
        if not data.get("agents"):
            print("No active agents found.")
            return
            
        print(json.dumps(data, indent=2))
        
    except httpx.RequestError as e:
        print(f"❌ Request failed: Could not connect to orchestrator at {ORCHESTRATOR_URL}.")

if __name__ == "__main__":
    app() 