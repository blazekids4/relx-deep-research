import os
import sys
import time
import json
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
import glob

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


class PipelineExecutor:
    """Orchestrates the product analysis pipeline execution."""
    
    def __init__(self, output_base: str, dry_run: bool = False):
        self.output_base = output_base
        self.dry_run = dry_run
        self.start_time = None
        self.metrics = {
            "search_phase": {"status": "pending", "duration": None, "output_dir": None},
            "attributes_analysis_phase": {"status": "pending", "duration": None, "output_dir": None},
            "total_duration": None
        }
        
    def log(self, message: str, level: str = "INFO"):
        """Log message with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")
        
    def check_environment(self) -> bool:
        """Verify all required environment variables are set."""
        required_vars = [
            "PROJECT_ENDPOINT_MULTI_AGENT_EXPERIMENTS",
            "MODEL_DEPLOYMENT_NAME",
            # Add other required environment variables
        ]
        
        missing = []
        for var in required_vars:
            if not os.environ.get(var):
                missing.append(var)
                
        if missing:
            self.log(f"Missing required environment variables: {', '.join(missing)}", "ERROR")
            return False
            
        self.log("Environment check passed", "INFO")
        return True
        
    def check_dependencies(self) -> bool:
        """Verify required scripts exist."""
        required_scripts = [
            "agents_multi_w_bing.py",
            "agent_product_attributes_analyst.py",
            "data/pet_food_search.json"
        ]
        
        missing = []
        for script in required_scripts:
            if not os.path.exists(script):
                missing.append(script)
                
        if missing:
            self.log(f"Missing required files: {', '.join(missing)}", "ERROR")
            return False
            
        self.log("Dependencies check passed", "INFO")
        return True
        
    def run_multi_agent_search(self) -> Tuple[bool, Optional[str]]:
        """Execute the multi-agent Bing search system."""
        self.log("Starting multi-agent search phase...", "INFO")
        phase_start = time.time()
        
        if self.dry_run:
            self.log("DRY RUN: Would execute agents_multi_w_bing.py", "INFO")
            return True, None
            
        try:
            # Run the multi-agent search script
            result = subprocess.run(
                [sys.executable, "agents_multi_w_bing.py"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Parse output to find the results directory
            output_lines = result.stdout.splitlines()
            results_dir = None
            for line in output_lines:
                if "Results saved in" in line:
                    # Extract directory name from output
                    parts = line.split("Results saved in")
                    if len(parts) > 1:
                        results_dir = parts[1].strip().rstrip('/')
                        break
            
            if not results_dir:
                # Try to find the most recent results directory
                results_dir = self.get_most_recent_search_dir()
                
            if results_dir and os.path.exists(results_dir):
                duration = time.time() - phase_start
                self.metrics["search_phase"] = {
                    "status": "completed",
                    "duration": round(duration, 2),
                    "output_dir": results_dir
                }
                self.log(f"Search phase completed in {duration:.2f} seconds", "SUCCESS")
                self.log(f"Results directory: {results_dir}", "INFO")
                return True, results_dir
            else:
                raise Exception("Could not find search results directory")
                
        except subprocess.CalledProcessError as e:
            duration = time.time() - phase_start
            self.metrics["search_phase"] = {
                "status": "failed",
                "duration": round(duration, 2),
                "output_dir": None,
                "error": str(e)
            }
            self.log(f"Search phase failed: {e}", "ERROR")
            if e.stderr:
                self.log(f"Error output: {e.stderr}", "ERROR")
            return False, None
            
    def get_most_recent_search_dir(self) -> Optional[str]:
        """Find the most recent multi_agent_with_bing_product_analysis_* directory."""
        dirs = glob.glob("multi_agent_with_bing_product_analysis_*")
        if not dirs:
            return None
        return max(dirs, key=os.path.getctime)
        
    def run_attributes_analyst(self, search_dir: str) -> Tuple[bool, Optional[str]]:
        """Execute the Product Attributes Analyst to generate reports."""
        self.log("Starting Product Attributes Analyst phase...", "INFO")
        phase_start = time.time()
        
        # Create reports directory under the main output base
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        reports_dir = os.path.join(self.output_base, f"product_analysis_reports_{timestamp}")
        
        if self.dry_run:
            self.log(f"DRY RUN: Would execute Product Attributes Analyst (agent_product_attributes_analyst.py)", "INFO")
            self.log(f"  Input: {search_dir}", "INFO")
            self.log(f"  Output: {reports_dir}", "INFO")
            return True, reports_dir
            
        try:
            # Run the report generator script
            result = subprocess.run(
                [
                    sys.executable, 
                    "agent_product_attributes_analyst.py",
                    "--input-dir", search_dir,
                    "--output-dir", reports_dir
                ],
                capture_output=True,
                text=True,
                check=True
            )
            
            duration = time.time() - phase_start
            self.metrics["attributes_analysis_phase"] = {
                "status": "completed",
                "duration": round(duration, 2),
                "output_dir": reports_dir
            }
            self.log(f"Product Attributes Analysis completed in {duration:.2f} seconds", "SUCCESS")
            self.log(f"Reports directory: {reports_dir}", "INFO")
            
            # Print some of the output
            if result.stdout:
                self.log("Product Attributes Analyst output:", "INFO")
                for line in result.stdout.splitlines()[-10:]:  # Last 10 lines
                    print(f"  {line}")
                    
            return True, reports_dir
            
        except subprocess.CalledProcessError as e:
            duration = time.time() - phase_start
            self.metrics["attributes_analysis_phase"] = {
                "status": "failed",
                "duration": round(duration, 2),
                "output_dir": None,
                "error": str(e)
            }
            self.log(f"Report generation failed: {e}", "ERROR")
            if e.stderr:
                self.log(f"Error output: {e.stderr}", "ERROR")
            return False, None
            
    def create_pipeline_summary(self, search_dir: Optional[str], reports_dir: Optional[str]):
        """Create a summary of the pipeline execution."""
        summary_path = os.path.join(self.output_base, "pipeline_summary.json")
        
        summary = {
            "execution_time": datetime.now().isoformat(),
            "total_duration": self.metrics["total_duration"],
            "phases": self.metrics,
            "outputs": {
                "search_results": search_dir,
                "reports": reports_dir
            },
            "status": "completed" if all(
                phase.get("status") == "completed" 
                for phase in [self.metrics["search_phase"], self.metrics["attributes_analysis_phase"]]
            ) else "failed"
        }
        
        if not self.dry_run:
            os.makedirs(self.output_base, exist_ok=True)
            with open(summary_path, 'w') as f:
                json.dump(summary, f, indent=2)
            self.log(f"Pipeline summary saved to: {summary_path}", "INFO")
            
        # Also create a human-readable summary
        self.print_execution_summary(summary)
        
    def print_execution_summary(self, summary: Dict):
        """Print a formatted execution summary."""
        print("\n" + "="*60)
        print("PIPELINE EXECUTION SUMMARY")
        print("="*60)
        print(f"Status: {summary['status'].upper()}")
        print(f"Total Duration: {summary['total_duration']} seconds")
        print(f"\nPhase Details:")
        print(f"  Search Phase:")
        print(f"    Status: {summary['phases']['search_phase']['status']}")
        print(f"    Duration: {summary['phases']['search_phase']['duration']} seconds")
        print(f"    Output: {summary['phases']['search_phase']['output_dir']}")
        print(f"\n  Product Attributes Analysis Phase:")
        print(f"    Status: {summary['phases']['attributes_analysis_phase']['status']}")
        print(f"    Duration: {summary['phases']['attributes_analysis_phase']['duration']} seconds")
        print(f"    Output: {summary['phases']['attributes_analysis_phase']['output_dir']}")
        print("\n" + "="*60)
        
    def execute(self, skip_search: bool = False, search_dir: Optional[str] = None) -> bool:
        """Execute the complete pipeline."""
        self.start_time = time.time()
        self.log("Starting Product Analysis Pipeline", "INFO")
        
        # Check environment and dependencies
        if not self.check_environment() or not self.check_dependencies():
            return False
            
        # Phase 1: Multi-agent search (unless skipped)
        if skip_search or search_dir:
            if search_dir and os.path.exists(search_dir):
                self.log(f"Skipping search phase, using existing results: {search_dir}", "INFO")
                search_success = True
                actual_search_dir = search_dir
            else:
                self.log("No valid search directory provided", "ERROR")
                return False
        else:
            search_success, actual_search_dir = self.run_multi_agent_search()
            if not search_success:
                self.log("Search phase failed, aborting pipeline", "ERROR")
                return False
                
        # Phase 2: Product Attributes Analysis
        report_success, reports_dir = self.run_attributes_analyst(actual_search_dir)
        
        # Calculate total duration
        self.metrics["total_duration"] = round(time.time() - self.start_time, 2)
        
        # Create pipeline summary
        self.create_pipeline_summary(actual_search_dir, reports_dir)
        
        return search_success and report_success


def main():
    parser = argparse.ArgumentParser(
        description="Execute the complete product analysis pipeline"
    )
    parser.add_argument(
        "--skip-search", 
        action="store_true",
        help="Skip the multi-agent search phase"
    )
    parser.add_argument(
        "--search-dir",
        help="Use existing search results from this directory (implies --skip-search)"
    )
    parser.add_argument(
        "--output-base",
        help="Base directory for all outputs",
        default=f"product_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running"
    )
    
    args = parser.parse_args()
    
    # If search-dir is provided, automatically skip search
    if args.search_dir:
        args.skip_search = True
        
    # Create and run the pipeline
    executor = PipelineExecutor(args.output_base, args.dry_run)
    success = executor.execute(args.skip_search, args.search_dir)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()