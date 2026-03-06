from langgraph.graph import StateGraph, END
from agents.challenger.challenger_agent import challenger_node


def build_workflow():

    graph = StateGraph(dict)

    # Nodes
    graph.add_node("planner", planner_agent)

    graph.add_node("backend_engineer", backend_agent)
    graph.add_node("frontend_engineer", frontend_agent)
    graph.add_node("security_engineer", security_agent)
    graph.add_node("sre_engineer", sre_agent)

    graph.add_node("challenger", challenger_agent)

    graph.add_node("judge", judge_agent)

    # Execution flow
    graph.set_entry_point("planner")

    graph.add_edge("planner", "backend_engineer")
    graph.add_edge("backend_engineer", "frontend_engineer")
    graph.add_edge("frontend_engineer", "security_engineer")
    graph.add_edge("security_engineer", "sre_engineer")

    # Week-6 addition
    graph.add_edge("sre_engineer", "challenger")

    graph.add_edge("challenger", "judge")

    graph.add_edge("judge", END)
    graph.add_node("challenger", challenger_node)

    return graph.compile()
