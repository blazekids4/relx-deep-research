from http import client
import os
import json
import time
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional
import re
import glob

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()


def get_most_recent_results_dir(base_dir: str = ".") -> str:
    """Find the most recent multi_agent_with_bing_results_* directory."""
    dirs = glob.glob(os.path.join(base_dir, "multi_agent_with_bing_results_*"))
    if not dirs:
        raise FileNotFoundError("No multi_agent_with_bing_results_* directories found.")

    # Sort by directory creation time, most recent first
    return max(dirs, key=os.path.getctime)


def load_combined_results(input_dir: str) -> Dict[str, List]:
    """Load combined agent results from the specified directory."""
    combined_file = os.path.join(input_dir, "combined_agent_results.json")
    if not os.path.exists(combined_file):
        raise FileNotFoundError(f"Combined results file not found: {combined_file}")
    
    with open(combined_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_product_data_by_id(combined_results: Dict[str, List], product_index: int) -> Dict:
    """Extract all data for a specific product across all agent roles."""
    product_data = {}
    
    # Find the first role that has results
    first_role = next(iter(combined_results.keys()))
    if not first_role or not combined_results[first_role]:
        raise ValueError("No agent results found")
    
    # Make sure product index is valid
    if product_index >= len(combined_results[first_role]):
        raise IndexError(f"Product index {product_index} out of range")
    
    # Extract basic product info from the first role
    product_info = combined_results[first_role][product_index]["product"]
    product_data["product_info"] = product_info
    
    # Extract role-specific results for this product
    product_data["agent_results"] = {}
    for role, results in combined_results.items():
        if product_index < len(results):
            product_data["agent_results"][role] = results[product_index]
    
    return product_data


def generate_analysis_prompt(product_data: Dict) -> str:
    """Generate a prompt for the Foundry model to analyze product data."""
    product_info = product_data["product_info"]["search_params"]
    
    prompt = f"""You are a product data analysis expert. Analyze the following information collected by multiple specialized agents about this product:

            Product Basic Information:
            - UPC: {product_info['upc']}
            - Product Name: {product_info['short_desc']}
            - Description: {product_info['long_desc']}

            """
    
    # Add role-specific data to the prompt
    for role, result in product_data["agent_results"].items():
        prompt += f"\n## {role.upper()} AGENT RESULTS:\n"
        prompt += f"Response: {result['response']}\n"
        prompt += f"Discovered attributes: {', '.join(result['discovered_attributes'])}\n"
        prompt += f"Citations: {', '.join(result['citations'])}\n"
    
    prompt += """
            Based on the above information, please provide:

            1. ANALYSIS: A comprehensive analysis of what information was returned about this product. What key facts did we learn? What categories of information were covered well?

            2. QUALITY ASSESSMENT: An evaluation of the quality and completeness of the agent responses. Were there gaps, inconsistencies, or areas where more information is needed? How reliable do the sources appear to be?

            3. COMPLETE ATTRIBUTES LIST: A consolidated, deduplicated list of all attributes discovered across all agents.

            4. CATEGORIZED BREAKDOWN: Group the attributes by logical categories (e.g., Basic Information, Nutrition Facts, Ingredients, etc.)

            Format your response as clear sections with markdown headers.
            """
    
    return prompt

   
def call_foundry_model(project_client: AIProjectClient, prompt: str) -> Dict:
    """Call the Foundry model to analyze the product data."""
    
    try:
        # Get the model deployment name
        # model_deployment_name = os.environ.get("MODEL_O3_DEPLOYMENT_NAME")
        # if not model_deployment_name:
        #     raise ValueError("MODEL_O3_DEPLOYMENT_NAME environment variable is required")
        
        model_deployment_name = os.environ.get("MODEL_ROUTER_DEPLOYMENT")
        if not model_deployment_name:
            raise ValueError("MODEL_ROUTER_DEPLOYMENT environment variable is required")

        # Get the Azure OpenAI client from the Foundry project
        openai_client = project_client.get_openai_client(api_version="2024-12-01-preview")

        # Call the model with the prompt
        response = openai_client.chat.completions.create(
            model=model_deployment_name,
            messages=[
                {"role": "system", "content": "You are a product data analysis expert providing comprehensive reports."},
                {"role": "user", "content": prompt}
            ],
        )

        return {
            "content": response.choices[0].message.content,
            "status": "completed"
        }
    except Exception as e:
        return {
            "content": f"Error generating analysis: {str(e)}",
            "status": "error",
            "error": str(e)
        }

def save_product_report(product_data: Dict, analysis_result: Dict, output_dir: str, product_index: int) -> Dict:
    """Save the product report in both Markdown and JSON formats."""
    os.makedirs(output_dir, exist_ok=True)
    
    product_info = product_data["product_info"]["search_params"]
    product_name = re.sub(r'[^\w\s-]', '', product_info['short_desc'])
    product_name = re.sub(r'\s+', '_', product_name).lower()
    
    # Generate JSON report
    json_report = {
        "product_info": product_data["product_info"],
        "analysis": analysis_result["content"],
        "analysis_metrics": analysis_result["metrics"],
        "status": analysis_result["status"],
        "error": analysis_result.get("error", None),
        "agent_results": {
            role: {
                "discovered_attributes": result["discovered_attributes"],
                "citations": result["citations"]
            }
            for role, result in product_data["agent_results"].items()
        }
    }
    
    json_path = os.path.join(output_dir, f"product_{product_index+1:03d}_{product_name}_report.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_report, f, indent=2)
    
    # Generate Markdown report
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md_content = f"# Product Report: {product_info['short_desc']}\n\n"
    md_content += f"**Generated on:** {timestamp}\n"
    md_content += f"**UPC:** {product_info['upc']}\n"
    if product_info['long_desc']:
        md_content += f"**Description:** {product_info['long_desc']}\n\n"
    
    md_content += f"## Analysis\n\n"
    md_content += f"{analysis_result['content']}\n\n"
    
    md_content += "## Agent Data Sources\n\n"
    for role, result in product_data["agent_results"].items():
        md_content += f"### {role.capitalize()} Agent\n"
        md_content += f"**Citations:**\n"
        for citation in result["citations"]:
            md_content += f"- {citation}\n"
        md_content += "\n"
    
    md_path = os.path.join(output_dir, f"product_{product_index+1:03d}_{product_name}_report.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    
    return {
        "json_path": json_path,
        "md_path": md_path
    }

def generate_summary_report(all_results: List[Dict], output_dir: str) -> str:
    """Generate a summary report of all products."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    md_content = f"# Product Reports Summary\n\n"
    md_content += f"**Generated on:** {timestamp}\n"
    md_content += f"**Total Products:** {len(all_results)}\n\n"
    
    md_content += "## Products Analyzed\n\n"
    for i, result in enumerate(all_results):
        product_info = result["product_data"]["product_info"]["search_params"]
        md_content += f"{i+1}. **{product_info['short_desc']}** (UPC: {product_info['upc']})\n"
        md_content += f"   - [JSON Report]({os.path.basename(result['report_paths']['json_path'])})\n"
        md_content += f"   - [Markdown Report]({os.path.basename(result['report_paths']['md_path'])})\n"
        md_content += f"   - Status: {result['analysis_result']['status']}\n\n"
    
    summary_path = os.path.join(output_dir, "summary_report.md")
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    
    return summary_path


def main():
    parser = argparse.ArgumentParser(description="Generate comprehensive product reports from combined agent results.")
    parser.add_argument("--input-dir", help="Directory containing combined_agent_results.json")
    parser.add_argument("--output-dir", help="Directory to save the reports")
    args = parser.parse_args()
    
    # Determine input directory
    input_dir = args.input_dir if args.input_dir else get_most_recent_results_dir()
    print(f"Using input directory: {input_dir}")
    
    # Determine output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir if args.output_dir else f"product_analysis_reports_{timestamp}"
    print(f"Using output directory: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # Load combined agent results
        combined_results = load_combined_results(input_dir)
        print(f"Loaded combined results with {len(combined_results)} agent roles")
        
        # Initialize Foundry project client
        project_endpoint = os.environ.get("MODEL_ROUTER_ENDPOINT")
        if not project_endpoint:
            raise ValueError("MODEL_ROUTER_ENDPOINT environment variable is required")

        project_client = AIProjectClient(
            endpoint=project_endpoint,
            credential=DefaultAzureCredential(),
        )
        
        # Process each product
        all_results = []
        first_role = next(iter(combined_results.keys()))
        total_products = len(combined_results[first_role])
        
        for i in range(total_products):
            try:
                print(f"\nProcessing product {i+1}/{total_products}")
                
                # Extract product data
                product_data = get_product_data_by_id(combined_results, i)
                product_name = product_data["product_info"]["search_params"]["short_desc"]
                print(f"Product: {product_name}")
                
                # Generate analysis prompt
                prompt = generate_analysis_prompt(product_data)
                
                # Call Foundry model
                print(f"Calling Foundry model for analysis...")
                analysis_result = call_foundry_model(project_client, prompt)
                print(f"Analysis status: {analysis_result['status']}")
                
                # Save reports
                report_paths = save_product_report(product_data, analysis_result, output_dir, i)
                print(f"Saved report to {report_paths['md_path']}")
                
                all_results.append({
                    "product_data": product_data,
                    "analysis_result": analysis_result,
                    "report_paths": report_paths
                })
                
            except Exception as e:
                print(f"Error processing product {i+1}: {str(e)}")
        
        # Generate summary report
        summary_path = generate_summary_report(all_results, output_dir)
        print(f"\nGenerated summary report: {summary_path}")
        print(f"\nAll reports saved to: {output_dir}")
        
    except Exception as e:
        print(f"Error in product report generation: {str(e)}")
        raise


if __name__ == "__main__":
    main()