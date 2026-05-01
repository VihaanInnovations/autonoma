from typing import Dict, Any, Literal

class LLMRouter:
    def __init__(self, user_config: Dict[str, Any]):
        self.config = user_config
    
    def route_analysis(self) -> Literal["local", "cloud", "both", "none"]:
        """
        Decide which LLM to use based on config and system state.
        """
        enable_local = self.config.get("enable_local_llm", False)
        enable_cloud = self.config.get("enable_cloud_llm", True)
        preference = self.config.get("modelPreference", "auto")
        
        # Simple Logic for MVP
        if preference == "local":
            return "local" if enable_local else "none"
        elif preference == "cloud":
            return "cloud" if enable_cloud else "none"
        else: # auto
            if enable_local and enable_cloud:
                return "both" # Run parallel or fallback? For full analysis we often want both insights.
            elif enable_cloud:
                return "cloud"
            elif enable_local:
                return "local"
            
        return "none"
