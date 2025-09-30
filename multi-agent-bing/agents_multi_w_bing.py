import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import concurrent.futures
import re

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import BingGroundingTool, MessageRole, BingCustomSearchTool


def load_search_data(json_path: str) -> List[Dict]:
    """Load search simulation data from JSON file."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['products']


def create_search_prompt(product: Dict, role: str) -> str:
    """Create a role-specific search prompt from product data."""
    params = product['search_params']
    base_info = f"""Search for information about the following product:

    UPC: {params['upc']}
    Product Name: {params['short_desc']}
    Description: {params['long_desc']}

    """
    
    if role == 'ingredients':
        prompt = base_info + """
        Please find and provide ONLY:
        1. Complete ingredient list
        2. Brand name
        3. Product title/name
        4. Source URLs for the ingredient information

        Focus exclusively on ingredients and basic product identification.
        """
    elif role == 'nutrition':
        prompt = base_info + """
        Please find and provide ONLY nutrition-related information:
        1. Nutrition facts (calories, protein, fat, carbohydrates)
        2. Vitamins and minerals
        3. Guaranteed analysis (for pet foods)
        4. Any nutrition claims or certifications
        5. Source URLs for all nutrition data

        Focus exclusively on nutritional attributes.
        """
    elif role == 'reviews':
        prompt = base_info + """
        Please find and provide ONLY customer review information:
        1. Overall rating/score
        2. Number of reviews
        3. Key positive feedback themes
        4. Key negative feedback themes
        5. Representative review excerpts
        6. Links to review pages

        Focus exclusively on customer feedback and ratings.
        """
    else:  # all_attributes
        prompt = base_info + """
        Please find and provide ALL available information:
        1. Complete product details (title, brand, SKU)
        2. Full ingredient list
        3. Nutrition facts
        4. Package sizes and variants
        5. Customer reviews and ratings
        6. Certifications
        7. Pricing information
        8. Any other relevant attributes

        Be exhaustive and cite sources for each piece of information.
        """
    
    return prompt + "\nIMPORTANT: For EVERY piece of information, include the COMPLETE URL where you found it. Format as 'Source: https://example.com' right after each section. Do NOT use numbered references like [1] without also including the full URL."


def extract_attributes(text: str) -> List[str]:
    """Extract a raw, inclusive list of attribute names from the response text.
    Uses simple heuristics: markdown headings, bolded labels, and lines with a "Key: Value" pattern.
    Returns a de-duplicated, sorted list of attribute names discovered in the text.
    """
    if not text:
        return []

    attributes = set()
    lines = text.splitlines()

    heading_re = re.compile(r"^\s*#{1,6}\s*([^\n#]{1,100})")
    bold_label_re = re.compile(r"\*\*\s*([^*:\n]{1,100}?)\s*\*\*\s*:")
    key_colon_re = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 &/()\-_.]{0,100}?)\s*:\s*")

    for line in lines:
        m = heading_re.match(line)
        if m:
            attr = m.group(1).strip()
            attributes.add(attr)
            continue

        m = bold_label_re.search(line)
        if m:
            attr = m.group(1).strip()
            attributes.add(attr)
            continue

        m = key_colon_re.match(line)
        if m:
            attr = m.group(1).strip()
            if len(attr) > 1:
                attributes.add(attr)

    bullet_label_re = re.compile(r"^\s*[-*+]\s*([^:\n]{1,60}?):")
    for line in lines:
        m = bullet_label_re.match(line)
        if m:
            attributes.add(m.group(1).strip())

    return sorted(attributes)


def get_or_create_agent_for_role(agents_client: AgentsClient, role_name: str, instruction: str, tool, config_filename: Optional[str] = None) -> Tuple[object, bool]:
    """Get or create an agent tailored for a specific role.
    Persists agent id to a role-specific config file so future runs reuse the agent.
    """
    cfg_file = config_filename or f"bing_agent-4.1_config_{role_name}.json"
    agent_name = f"bing-agent-4.1-{role_name}"

    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                agent_id = cfg.get('agent_id')
            if agent_id:
                try:
                    agent = agents_client.get_agent(agent_id)
                    print(f"Found existing agent for role '{role_name}': {agent_id} (name: {cfg.get('agent_name', agent_name)})")
                    return agent, False
                except Exception as e:
                    print(f"Could not retrieve agent {agent_id} for role {role_name}: {e}. Will create a new one.")
        except Exception as e:
            print(f"Error reading agent config {cfg_file}: {e}")

    print(f"Creating new agent for role: {role_name}...")
    tool_defs = tool.definitions if tool is not None else []

    agent = agents_client.create_agent(
        model=os.environ.get("MODEL_DEPLOYMENT_NAME"),
        name=agent_name,
        instructions=instruction,
        tools=tool_defs,
    )

    with open(cfg_file, 'w', encoding='utf-8') as f:
        json.dump({'agent_id': agent.id, 'agent_name': agent_name}, f, indent=2)

    print(f"Created new agent for role '{role_name}': {agent.id}")
    return agent, True


def build_role_tools(project_client: AIProjectClient) -> dict:
    """Construct tool instances for each agent role, using distinct Bing custom configs per role.
    
    Environment variables for custom role-specific Bing configurations:
    
    All Attributes agent:
      - Uses BingGroundingTool (regular Bing search)
    
    Ingredients agent:
      - BING_INGREDIENTS_CONNECTION_NAME - Connection name for ingredients-focused Bing
      - BING_INGREDIENTS_INSTANCE_NAME - Custom search instance name for ingredients
    
    Nutrition agent:
      - BING_NUTRITION_CONNECTION_NAME - Connection name for nutrition-focused Bing
      - BING_NUTRITION_INSTANCE_NAME - Custom search instance name for nutrition
    
    Reviews agent:
      - Uses BingGroundingTool (regular Bing search)
    
    Fallback options:
      - If role-specific variables are missing, falls back to:
      - BING_CUSTOM_CONNECTION_NAME - Default connection name
      - BING_CUSTOM_INSTANCE_NAME - Default instance name
    """
    roles = {}

    def _get_custom_tool_for_role(role: str):
        # First try role-specific naming convention
        primary_conn_var = f"BING_{role.upper()}_CONNECTION_NAME"
        primary_instance_var = f"BING_{role.upper()}_INSTANCE_NAME"
        
        # Fall back to legacy naming convention
        legacy_conn_var = f"BING_CUSTOM_CONNECTION_NAME_{role.upper()}"
        legacy_instance_var = f"BING_CUSTOM_INSTANCE_NAME_{role.upper()}"
        
        # Final fallback to default vars
        default_conn_var = "BING_CUSTOM_CONNECTION_NAME"
        default_instance_var = "BING_CUSTOM_INSTANCE_NAME"
        
        # Try each naming convention in order of preference
        conn_env = (os.environ.get(primary_conn_var) or 
                    os.environ.get(legacy_conn_var) or 
                    os.environ.get(default_conn_var))
        
        instance_env = (os.environ.get(primary_instance_var) or 
                       os.environ.get(legacy_instance_var) or 
                       os.environ.get(default_instance_var))
        
        if conn_env:
            try:
                connection = project_client.connections.get(name=conn_env)
                conn_id = connection.id
                print(f"Resolved connection for {role}: {conn_id} (instance: {instance_env})")
                print(f"Using: Connection={conn_env}, Instance={instance_env}")
                return BingCustomSearchTool(connection_id=conn_id, instance_name=instance_env)
            except Exception as e:
                print(f"Could not resolve custom connection '{conn_env}' for {role}: {e}")
                return None
        return None

    # Regular Bing search (not custom) for all_attributes
    print("Using BingGroundingTool (regular Bing Search) for 'all_attributes' role")
    # Get the Bing Grounding connection name from environment variables
    grounding_conn_name = os.environ.get("BING_GROUNDED_CONNECTION_NAME")
    if grounding_conn_name:
        try:
            connection = project_client.connections.get(name=grounding_conn_name)
            print(f"Resolved Bing Grounding connection: {connection.id} (name: {grounding_conn_name})")
            roles['all_attributes'] = BingGroundingTool(connection_id=connection.id)
        except Exception as e:
            print(f"Could not resolve Bing Grounding connection '{grounding_conn_name}': {e}")
            print("Falling back to default BingGroundingTool without explicit connection")
            roles['all_attributes'] = BingGroundingTool()
    else:
        print("No BING_GROUNDED_CONNECTION_NAME found in environment variables")
        print("Using default BingGroundingTool without explicit connection")
        roles['all_attributes'] = BingGroundingTool()
    
    # Get custom Bing tools for specialized agents
    roles['ingredients'] = _get_custom_tool_for_role('ingredients')
    roles['nutrition'] = _get_custom_tool_for_role('nutrition') 
    roles['reviews'] = _get_custom_tool_for_role('reviews')

    return roles


def extract_citations(text: str) -> List[str]:
    """Extract citations from text using multiple patterns to catch different formats."""
    if not text:
        return []
    
    citations = set()
    
    # Pattern 1: Direct URLs
    url_re = re.compile(r"https?://[\w\-._~:/?#[\]@!$&'()*+,;=%]+")
    urls = url_re.findall(text)
    for url in urls:
        # Clean up URL if it ends with closing parenthesis that's not part of the URL
        if url.endswith(')') and '(' not in url.split('/')[-1]:
            url = url[:-1]
        citations.add(url)
    
    # Pattern 2: Markdown links [text](url)
    markdown_re = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    for match in markdown_re.finditer(text):
        citations.add(match.group(2))
    
    # Pattern 3: Citation references with various formats
    # Common formats: [1], [Source 1], [1][2], etc.
    bracket_ref_re = re.compile(r'\[([^\]]+)\]')
    bracket_refs = set(bracket_ref_re.findall(text))
    ref_markers = {"source", "reference", "ref", "citation"}
    
    # Only add a note about bracket references if they look like citations (not just random bracketed text)
    has_reference_brackets = any(
        ref.isdigit() or 
        any(marker in ref.lower() for marker in ref_markers)
        for ref in bracket_refs
    )
    
    # Pattern 4: Footnote-style citations often used by Azure AI agents
    footnote_re = re.compile(r'(?:^|\s)\^(\d+)(?:\s|$)')
    has_footnotes = bool(footnote_re.search(text))
    
    # Check if there's a "Sources" or "References" section which might have citations
    lines = text.lower().splitlines()
    has_source_section = any("sources:" in line or "references:" in line for line in lines)
    
    # If we found reference patterns but no URLs, note it
    if (has_reference_brackets or has_footnotes or has_source_section) and not citations:
        citations.add("NOTE: Text contains citation references but no extractable URLs")
    
    return sorted(citations)

def process_batch_bing_search_for_agent(
    products: List[Dict],
    agents_client: AgentsClient,
    agent_id: str,
    thread_id: str,
    output_base_path: str,
    role: str
) -> List[Dict]:
    """Run a per-role processing pass over the products, extract citations, attributes, and save outputs."""
    os.makedirs(output_base_path, exist_ok=True)

    results = []

    for i, product in enumerate(products, 1):
        print(f"\n[{role}] Processing product {i}/{len(products)}: UPC={product['search_params']['upc']}")

        try:
            # Create role-specific prompt - passing the role parameter
            prompt = create_search_prompt(product, role)
            
            # Since the prompt is already role-specific, we don't need the extra prefix
            full_prompt = prompt

            agents_client.messages.create(thread_id=thread_id, role="user", content=full_prompt)

            run = agents_client.runs.create(thread_id=thread_id, agent_id=agent_id)
            timeout = int(os.getenv("BATCH_TIMEOUT_SECONDS", "120"))
            heartbeat_interval = 10
            loop_seconds = 0

            while run.status in ("queued", "in_progress"):
                time.sleep(1)
                loop_seconds += 1
                if loop_seconds % heartbeat_interval == 0:
                    print(f"[{role}] Still processing product {i}, elapsed {loop_seconds}s")
                if loop_seconds >= timeout:
                    print(f"[{role}] Timeout after {timeout}s for product {i}, aborting run.")
                    break
                run = agents_client.runs.get(thread_id=thread_id, run_id=run.id)

                response = agents_client.messages.get_last_message_by_role(thread_id=thread_id, role=MessageRole.AGENT)
                if response and response.text_messages:
                    print(f"[{role}] Partial response so far:\n{response.text_messages[-1].text.value}\n")
                    response_text = "\n".join(t.text.value for t in response.text_messages)


            discovered = extract_attributes(response_text)

            citations = extract_citations(response_text)

            result = {
                "product": product,
                "prompt": full_prompt,
                "response": response_text,
                "status": run.status,
                "error": str(run.last_error) if run.status == "failed" else None,
                "discovered_attributes": discovered,
                "citations": citations,
                "role": role,
            }

            results.append(result)

            # Save per-agent, per-product markdown
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            upc = product['search_params']['upc']
            filename = f"{output_base_path}/{role}_search_{i:03d}_{upc}_{timestamp}.md"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# [{role}] Product Search Result\n\n")
                f.write(f"**Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**Agent Role:** {role}\n")
                f.write(f"**Status:** {result['status']}\n\n")
                if result['error']:
                    f.write(f"**Error:** {result['error']}\n\n")

                f.write("## Search Parameters\n")
                params = product['search_params']
                f.write(f"- **UPC:** {params['upc']}\n")
                f.write(f"- **Product:** {params['short_desc']}\n")
                f.write(f"- **Description:** {params['long_desc']}\n\n")

                f.write("## Execution Metrics\n")
                metrics_local = result['metrics']
                f.write(f"- **Time to First Token:** {metrics_local['time_to_first_token']} seconds\n")
                f.write(f"- **Total Time:** {metrics_local['total_time']} seconds\n")
                f.write(f"- **Tokens In:** {metrics_local['tokens_in']}\n")
                f.write(f"- **Tokens Out:** {metrics_local['tokens_out']}\n")
                f.write(f"- **Total Tokens:** {metrics_local['total_tokens']}\n\n")

                f.write("## Agent Response\n")
                f.write(result['response'] or "(no response)")
                f.write("\n\n")

                f.write("## Citations\n")
                if citations:
                    for c in citations:
                        f.write(f"- {c}\n")
                else:
                    f.write("- None detected in response\n")

                f.write("\n## Discovered Attributes (raw)\n")
                if discovered:
                    for a in discovered:
                        f.write(f"- {a}\n")
                else:
                    f.write("- None detected\n")

        except Exception as e:
            print(f"[{role}] Error processing product {i}: {str(e)}")
            results.append({
                "product": product,
                "prompt": prompt if 'prompt' in locals() else None,
                "response": "",
                "status": "error",
                "error": str(e),
                "discovered_attributes": [],
                "citations": [],
                "role": role,
            })

    out_json = f"{output_base_path}/{role}_batch_search_results.json"
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    all_attrs = set()
    for r in results:
        for a in r.get('discovered_attributes', []):
            all_attrs.add(a)
    attr_file = f"{output_base_path}/{role}_batch_search_attributes.json"
    with open(attr_file, 'w', encoding='utf-8') as f:
        json.dump(sorted(all_attrs), f, indent=2)

    return results


def main():
    try:
        project_client = AIProjectClient(
            endpoint=os.environ["PROJECT_ENDPOINT_MULTI_AGENT_EXPERIMENTS"],
            credential=DefaultAzureCredential(),
        )

        role_tools = build_role_tools(project_client)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        top_output_dir = f"multi_agent_with_bing_results_{timestamp}"
        os.makedirs(top_output_dir, exist_ok=True)

        products = load_search_data("data/pet_food_search.json")
        print(f"Loaded {len(products)} products from pet_food_search.json")

        with project_client:
            with project_client.agents as agents_client:
                role_instructions = {
                    'all_attributes': 
                        "You are an exhaustive product attribute discovery agent. When given product info, find every attribute available: title, brand, full ingredients, nutrition facts, packaging, weights, SKUs, flavors, certifications, and customer feedback. ALWAYS include complete URLs for your sources - not just reference numbers. For every piece of information, include the full URL you found it on. Format citations as 'Source: https://example.com' directly after the information.",
                    
                    'ingredients': 
                        "You are a product ingredients extraction agent. Only return the ingredient list(s) and high-level product descriptors such as brand and product title. For each ingredient list found, include the complete URL where you found it. Always use full URLs for citations, not just reference numbers or footnotes. Format citations as 'Source: https://example.com' directly after each section.",
                    
                    'nutrition': 
                        "You are a nutrition attributes agent. Extract nutrition facts, calorie counts, macro/micronutrients, guaranteed analysis (for pet foods), and any nutrition-related claims. Always include the complete URL where you found each piece of information. Include full URLs for all sources, not just reference numbers. Format citations as 'Source: https://example.com' directly after the relevant information.",
                    
                    'reviews': 
                        "You are a customer reviews aggregation agent. Locate customer review pages, aggregate ratings, extract representative positive and negative excerpts, and provide a detailed summary and recommendations. Always include the complete URLs for each review site you reference. For every customer review or rating, include the full URL where it was found. Format citations as 'Source: https://example.com' directly after quoting a review.",
                    
                }

                agents_by_role = {}
                for role, instruction in role_instructions.items():
                    tool = role_tools.get(role)
                    agent, is_new = get_or_create_agent_for_role(agents_client, role, instruction, tool)
                    agents_by_role[role] = {
                        'agent': agent,
                        'tool': tool,
                        'is_new': is_new,
                    }

                threads_by_role = {}
                for role, meta in agents_by_role.items():
                    thread = agents_client.threads.create()
                    threads_by_role[role] = thread.id
                    print(f"Created thread for role '{role}': {thread.id}")

                with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents_by_role)) as executor:
                    future_to_role = {}
                    for role, meta in agents_by_role.items():
                        out_dir = os.path.join(top_output_dir, role)
                        os.makedirs(out_dir, exist_ok=True)

                        future = executor.submit(
                            process_batch_bing_search_for_agent,
                            products,
                            agents_client,
                            meta['agent'].id,
                            threads_by_role[role],
                            out_dir,
                            role,
                        )
                        future_to_role[future] = role

                    all_agent_results = {}
                    for fut in concurrent.futures.as_completed(future_to_role):
                        role = future_to_role[fut]
                        try:
                            agent_results = fut.result()
                            all_agent_results[role] = agent_results
                            print(f"Completed processing for role: {role}")
                        except Exception as e:
                            print(f"Error in role {role}: {e}")

                combined_file = os.path.join(top_output_dir, 'combined_agent_results.json')
                with open(combined_file, 'w', encoding='utf-8') as f:
                    json.dump(all_agent_results, f, indent=2)

                print(f"Multi-agent processing complete. Results saved in {top_output_dir}/")

    except Exception as e:
        print(f"Error in multi-agent main: {str(e)}")
        raise


if __name__ == "__main__":
    main()
