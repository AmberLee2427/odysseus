import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class KnowledgeGraphService:
    """
    Service to query the Logseq Project-to-Entity context index.

    Important terminology:
    - ``projects`` in SQLite owns structural identity (project_id, owner,
      lifecycle).
    - Logseq/project_manifest.json is the human-editable mirror/context cache.
      It may contain the whole visible project control-panel state, but it
      should not silently rewrite structural identity fields.
    """

    def __init__(self, manifest_path: str):
        self.manifest_path = Path(manifest_path)
        self.manifest: Dict[str, Any] = {}
        self.load_manifest()

    def load_manifest(self) -> None:
        """Loads the JSON manifest from disk."""
        try:
            if not self.manifest_path.exists():
                logger.error(f"Manifest not found at {self.manifest_path}")
                return

            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                self.manifest = json.load(f)
            logger.info(f"Successfully loaded Knowledge Graph manifest from {self.manifest_path}")
        except Exception as e:
            logger.error(f"Failed to load Knowledge Graph manifest: {e}")
            self.manifest = {}

    def get_project_context(self, project_name: str) -> Dict[str, Any]:
        """
        Returns the structured context payload for a specific project.
        
        Args:
            project_name: The name of the project (e.g., 'Odysseus')
            
        Returns:
            A dictionary containing file paths for pages, tags, and entities, 
            or an empty dict if the project is not found.
        """
        # The manifest keys are the project names. 
        # We'll do a case-insensitive lookup just in case.
        project_data = None
        for key in self.manifest.keys():
            if key.lower() == project_name.lower():
                project_data = self.manifest[key]
                break
        
        if not project_data:
            logger.warning(f"Project '{project_name}' not found in Knowledge Graph manifest.")
            return {}

        return project_data

    def get_context_by_tag(self, tag: str) -> List[str]:
        """
        Returns all file paths associated with a specific tag across all projects.
        
        Args:
            tag: The tag to search for (e.g., 'cosci')
            
        Returns:
            A list of file paths.
        """
        tag_cleaned = tag.strip().lstrip('#').replace('[[', '').replace(']]', '')
        found_paths = []

        for project_name, data in self.manifest.items():
            tags_dict = data.get("tags", {})
            for t, paths in tags_dict.items():
                if t.strip().lstrip('#').replace('[[', '').replace(']]', '') == tag_cleaned:
                    found_paths.extend(paths)
        
        return list(set(found_paths)) # Return unique paths

    def list_projects_summary(self) -> List[str]:
        """
        Returns a list of all known projects with their descriptions.
        Used for high-level context awareness (the 'Project Directory').
        """
        summary = []
        for name, data in self.manifest.items():
            description = data.get("description", "No description provided.")
            summary.append(f"{name}: {description}")
        return summary

# Example usage/Test block
if __name__ == "__main__":
    # For testing purposes, we point to the manifest we just created
    TEST_MANIFEST = "odysseus/data/logseq-graph/project_manifest.json"
    kg = KnowledgeGraphService(TEST_MANIFEST)
    
    print(f"Available Projects: {kg.list_projects()}")
    
    project = "Odysseus"
    print(f"\nContext for '{project}':")
    print(json.dumps(kg.get_project_context(project), indent=2))
    
    tag = "cosci"
    print(f"\nPaths for tag '{tag}':")
    print(kg.get_context_by_tag(tag))
