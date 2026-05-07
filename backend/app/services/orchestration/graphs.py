from langgraph.graph import END, START, StateGraph

from app.services.orchestration.persistence import StatePersistence
from app.services.orchestration.state import AutoERPGeneratorState, JDECopilotState, RouteDecision


class WorkflowRegistry:
    def __init__(self, persistence: StatePersistence | None = None) -> None:
        self.persistence = persistence or StatePersistence()

    def route_copilot_message(self, state: JDECopilotState) -> RouteDecision:
        try:
            if state.error_message:
                return RouteDecision(agent="error_handler", next_step="recover", metadata={"reason": state.error_message})
            if state.execution_needed or state.decision == "action":
                return RouteDecision(agent=f"{state.current_module}_action_agent", next_step="execute_action", metadata={"action_type": state.action_type})
            return RouteDecision(agent=f"{state.current_module}_query_agent", next_step="answer_query")
        finally:
            self.persistence.save("jde_copilot", state.query_id, state)

    def route_generator_step(self, state: AutoERPGeneratorState) -> RouteDecision:
        step_map = {
            1: ("requirements_parser", "parse_requirements"),
            2: ("schema_designer", "design_schema"),
            3: ("code_generator", "generate_backend"),
            4: ("config_generator", "generate_configs"),
            5: ("master_data_builder", "prepare_master_data"),
            6: ("delivery_packager", "finalize"),
        }
        try:
            if state.error:
                return RouteDecision(agent="error_handler", next_step="recover", metadata={"reason": state.error})
            agent, next_step = step_map.get(state.current_step, ("delivery_packager", "finalize"))
            return RouteDecision(agent=agent, next_step=next_step)
        finally:
            self.persistence.save("autoerp_generator", state.generation_id, state)

    def build_copilot_graph(self):
        graph = StateGraph(JDECopilotState)
        graph.add_node("route", self.route_copilot_message)
        graph.add_edge(START, "route")
        graph.add_edge("route", END)
        return graph.compile()

    def build_generator_graph(self):
        graph = StateGraph(AutoERPGeneratorState)
        graph.add_node("route", self.route_generator_step)
        graph.add_edge(START, "route")
        graph.add_edge("route", END)
        return graph.compile()

    def load_copilot_state(self, query_id: str) -> JDECopilotState | None:
        return self.persistence.load("jde_copilot", query_id, JDECopilotState)

    def load_generator_state(self, generation_id: str) -> AutoERPGeneratorState | None:
        return self.persistence.load("autoerp_generator", generation_id, AutoERPGeneratorState)

    def list_graphs(self) -> list[str]:
        return ["autoerp_generator_graph", "jde_copilot_graph"]
