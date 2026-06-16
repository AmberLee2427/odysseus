import os
import re
import json
from pathlib import Path
from collections import defaultdict

def scan_logseq_graph(graph_root: str):
    """
    Scans the Logseq graph directory and builds a mapping of projects and tags to file paths.
    """
    graph_path = Path(graph_root)
    if not graph_path.exists():
        raise ValueError(f"Graph root directory does not exist: {graph_root}")

    # Manifest structure:
    # {
    #   "Project Name": {
    #       "pages": ["path/to/page1.md", ...],
    #       "tags": {
    #           "tag1": ["path/to/page1.md", ...],
    #           "tag2": ["path/to/page2.md", ...]
    #       }
    #   }
    # }
    manifest = defaultdict(lambda: {"pages": [], "tags": defaultdict(list)})

    # Regex patterns for Logseq properties
    # Matches 'project:: [[Project Name]]' or 'project:: Project Name'
    project_pattern = re.compile(r'^project::\s*(?:\[\[)?([^\]\n]+)(?:\]\])?', re.MULTILINE)
    # Matches 'tags:: [[tag1]], [[tag2]]' or 'tags:: tag1, tag2'
    tags_pattern = re.compile(r'^tags::\s*(.*)', re.MULTILINE)

    print(f"Scanning graph at: {graph_path}")

    for md_file in graph_path.rglob("*.md"):
        relative_path = str(md_file.relative_to(graph_path))
        
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 1. Extract Project
            project_match = project_pattern.search(content)
            if project_match:
                project_name = project_match.group(1).strip()
                manifest[project_name]["pages"].append(relative_path)

                # 2. Extract Tags
                tags_match = tags_pattern.search(content)
                if tags_match:
                    tags_str = tags_match.group(1)
                    # Find all [[tag]] or just tag in the comma-separated list
                    # This regex looks for content inside [[ ]] or just word characters/dashes/etc
                    tags = re.findall(r'\[\[([^\]]+)\]\]|([^,\s]+)', tags_str)
                    
                    for t_match in tags:
                        # re.findall with multiple groups returns tuples
                        tag = (t_match[0] or t_match[1]).strip()
                        if tag:
                            # If a tag is found, add it to the project's tag map
                            # Note: We associate the tag with the project it belongs to
                            manifest[project_name]["tags"][tag].append(relative_path)

        except Exception as e:
            print(f"Error parsing {md_file}: {e}")

    # Convert defaultdict to regular dict for JSON serialization
    final_manifest = {}
    for project, data in manifest.items():
        final_manifest[project] = {
            "pages": data["pages"],
            "tags": dict(data["tags"])
        }

    return final_manifest

def main():
    # Define paths
    graph_root = "odysseus/data/logseq-graph"
    output_file = "odysseus/data/logseq-graph/project_manifest.json"

    try:
        manifest = scan_logseq_graph(graph_root)
        
        # Save manifest
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=4)
        
        print(f"Successfully scanned {len(manifest)} projects.")
        print(f"Manifest saved to: {output_file}")
        
    except Exception as e:
        print(f"Failed to scan graph: {e}")

if __name__ == "__main__":
    main()
