#!/usr/bin/env python3
"""
Interactive RAG Feature Comparison Dashboard
Allows toggling features and visualizing performance differences
"""

import os
import sys
import time
import json
import requests
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

# ANSI Colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

@dataclass
class TestResult:
    mode: str
    confidence: float
    num_chunks: int
    api_time_ms: float
    wall_time_ms: float
    total_tokens: int
    cost_usd: float
    iterations: int = 1
    converged: bool = False
    answer_preview: str = ""
    timestamp: str = ""

class RAGComparator:
    def __init__(self, base_url: str = "http://localhost:8888"):
        self.base_url = base_url
        self.api_base = f"{base_url}/api/rag"
        self.results: List[TestResult] = []

    def check_health(self) -> bool:
        """Check if backend is healthy"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except:
            return False

    def run_test(self, endpoint: str, mode_name: str, question: str, top_k: int = 10) -> TestResult:
        """Run a single test against an endpoint"""
        print(f"\n{Colors.YELLOW}Testing: {mode_name}{Colors.END}")

        start_time = time.time()

        try:
            response = requests.post(
                f"{self.api_base}/{endpoint}",
                json={
                    "question": question,
                    "top_k": top_k,
                    "include_timings": True
                },
                timeout=300
            )

            wall_time_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                print(f"{Colors.RED}Error: {response.status_code}{Colors.END}")
                raise Exception(f"API error: {response.status_code}")

            data = response.json()

            # Extract metrics
            result = TestResult(
                mode=mode_name,
                confidence=data.get('confidence', 0.0),
                num_chunks=data.get('num_chunks_retrieved', 0),
                api_time_ms=data.get('total_time_ms', 0.0),
                wall_time_ms=wall_time_ms,
                total_tokens=data.get('token_usage', {}).get('total', 0),
                cost_usd=data.get('token_cost_usd', 0.0),
                iterations=data.get('timings', {}).get('total_iterations', 1),
                converged=data.get('timings', {}).get('converged', False),
                answer_preview=data.get('answer', '')[:150],
                timestamp=datetime.now().strftime("%H:%M:%S")
            )

            self.print_result(result)
            self.results.append(result)

            return result

        except Exception as e:
            print(f"{Colors.RED}Test failed: {e}{Colors.END}")
            raise

    def print_result(self, result: TestResult):
        """Print formatted test result"""
        print(f"{Colors.CYAN}Results:{Colors.END}")
        print(f"  Answer: {result.answer_preview}...")
        print(f"  Confidence: {result.confidence:.4f}")
        print(f"  Chunks Retrieved: {result.num_chunks}")
        print(f"  API Time: {result.api_time_ms:.1f}ms")
        print(f"  Wall Time: {result.wall_time_ms:.1f}ms")
        print(f"  Total Tokens: {result.total_tokens}")
        print(f"  Cost: ${result.cost_usd:.6f}")

        if result.iterations > 1 or result.converged:
            print(f"  Iterations: {result.iterations}")
            print(f"  Converged: {result.converged}")

    def compare_all(self, question: str, top_k: int = 10) -> List[TestResult]:
        """Run all modes and compare"""
        print(f"\n{Colors.CYAN}{'='*60}{Colors.END}")
        print(f"{Colors.CYAN}Running Comprehensive Comparison{Colors.END}")
        print(f"{Colors.CYAN}{'='*60}{Colors.END}")
        print(f"\nQuestion: {question}\n")

        modes = [
            ("ask", "Standard RAG"),
            ("ask-hybrid", "Hybrid Search"),
            ("ask-iterative", "Self-RAG Iterative"),
            ("ask-smart", "Smart RAG")
        ]

        results = []
        for endpoint, name in modes:
            try:
                result = self.run_test(endpoint, name, question, top_k)
                results.append(result)
                time.sleep(1)  # Small delay between tests
            except Exception as e:
                print(f"{Colors.RED}Skipping {name} due to error{Colors.END}")

        return results

    def print_comparison_table(self, results: Optional[List[TestResult]] = None):
        """Print formatted comparison table"""
        if results is None:
            results = self.results

        if not results:
            print(f"{Colors.YELLOW}No results to compare yet{Colors.END}")
            return

        print(f"\n{Colors.HEADER}{'='*120}{Colors.END}")
        print(f"{Colors.HEADER}Comparison Summary{Colors.END}")
        print(f"{Colors.HEADER}{'='*120}{Colors.END}\n")

        # Header
        print(f"{Colors.BOLD}{'Mode':<20} {'Confidence':>12} {'Chunks':>8} {'API Time':>12} {'Wall Time':>12} {'Tokens':>10} {'Cost':>12} {'Iters':>6}{Colors.END}")
        print("-" * 120)

        # Find best values for highlighting
        best_conf = max(r.confidence for r in results)
        best_time = min(r.api_time_ms for r in results)
        best_tokens = min(r.total_tokens for r in results if r.total_tokens > 0)
        best_cost = min(r.cost_usd for r in results if r.cost_usd > 0)

        # Rows
        for r in results:
            conf_color = Colors.GREEN if r.confidence == best_conf else ""
            time_color = Colors.GREEN if r.api_time_ms == best_time else ""
            token_color = Colors.GREEN if r.total_tokens == best_tokens else ""
            cost_color = Colors.GREEN if r.cost_usd == best_cost else ""

            print(f"{r.mode:<20} "
                  f"{conf_color}{r.confidence:>12.4f}{Colors.END} "
                  f"{r.num_chunks:>8} "
                  f"{time_color}{r.api_time_ms:>12.1f}ms{Colors.END} "
                  f"{r.wall_time_ms:>12.1f}ms "
                  f"{token_color}{r.total_tokens:>10}{Colors.END} "
                  f"{cost_color}${r.cost_usd:>11.6f}{Colors.END} "
                  f"{r.iterations:>6}")

        print("")

        # Calculate relative improvements
        self.print_insights(results)

    def print_insights(self, results: List[TestResult]):
        """Print insights from comparison"""
        if len(results) < 2:
            return

        baseline = next((r for r in results if "Standard" in r.mode), results[0])

        print(f"{Colors.CYAN}Key Insights (vs {baseline.mode}):{Colors.END}\n")

        for r in results:
            if r == baseline:
                continue

            conf_delta = ((r.confidence - baseline.confidence) / abs(baseline.confidence) * 100) if baseline.confidence != 0 else 0
            time_delta = ((r.api_time_ms - baseline.api_time_ms) / baseline.api_time_ms * 100)
            token_delta = ((r.total_tokens - baseline.total_tokens) / baseline.total_tokens * 100) if baseline.total_tokens > 0 else 0

            print(f"{Colors.BOLD}{r.mode}:{Colors.END}")

            # Confidence
            if conf_delta > 0:
                print(f"  ✓ Confidence: {Colors.GREEN}+{conf_delta:.1f}%{Colors.END}")
            else:
                print(f"  ✗ Confidence: {Colors.RED}{conf_delta:.1f}%{Colors.END}")

            # Latency
            if time_delta < 0:
                print(f"  ✓ Latency: {Colors.GREEN}{time_delta:.1f}% faster{Colors.END}")
            else:
                print(f"  ✗ Latency: {Colors.YELLOW}+{time_delta:.1f}% slower{Colors.END}")

            # Tokens
            if token_delta < 0:
                print(f"  ✓ Tokens: {Colors.GREEN}{token_delta:.1f}% fewer{Colors.END}")
            elif token_delta > 0:
                print(f"  ✗ Tokens: {Colors.RED}+{token_delta:.1f}% more{Colors.END}")

            print()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            response = requests.get(f"{self.api_base}/cache/stats", timeout=5)
            return response.json()
        except:
            return {"error": "Failed to fetch cache stats"}

    def clear_cache(self):
        """Clear query cache"""
        try:
            response = requests.post(f"{self.api_base}/cache/clear", timeout=5)
            print(f"{Colors.GREEN}Cache cleared: {response.json()}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}Failed to clear cache: {e}{Colors.END}")

    def export_results(self, filename: str = "rag_comparison_results.json"):
        """Export results to JSON"""
        data = [
            {
                "mode": r.mode,
                "confidence": r.confidence,
                "num_chunks": r.num_chunks,
                "api_time_ms": r.api_time_ms,
                "wall_time_ms": r.wall_time_ms,
                "total_tokens": r.total_tokens,
                "cost_usd": r.cost_usd,
                "iterations": r.iterations,
                "converged": r.converged,
                "timestamp": r.timestamp
            }
            for r in self.results
        ]

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"{Colors.GREEN}Results exported to {filename}{Colors.END}")


def show_menu():
    """Display main menu"""
    print(f"\n{Colors.HEADER}{'='*60}{Colors.END}")
    print(f"{Colors.HEADER}RAG Feature Comparison Dashboard{Colors.END}")
    print(f"{Colors.HEADER}{'='*60}{Colors.END}\n")

    print("1) Test Standard RAG (baseline)")
    print("2) Test Hybrid Search (BM25 + Vector)")
    print("3) Test Iterative Self-RAG")
    print("4) Test Smart RAG (auto-selection)")
    print("5) Compare All Modes")
    print("6) Custom Comparison")
    print("7) View Comparison Table")
    print("8) View Cache Stats")
    print("9) Clear Cache")
    print("10) Export Results to JSON")
    print("11) Change Test Question")
    print("0) Exit\n")


def main():
    comparator = RAGComparator()

    # Default test question
    question = "Sir roberts fortune a novel, for what purpose he was confident of his own powers of cheating the uncle, and managing?"

    # Check backend health
    print(f"{Colors.BLUE}Checking backend health...{Colors.END}")
    if not comparator.check_health():
        print(f"{Colors.RED}Backend is not responding. Please start the backend first.{Colors.END}")
        sys.exit(1)

    print(f"{Colors.GREEN}✓ Backend is ready{Colors.END}")

    while True:
        show_menu()

        try:
            choice = input(f"{Colors.CYAN}Select option: {Colors.END}").strip()

            if choice == "1":
                comparator.run_test("ask", "Standard RAG", question)

            elif choice == "2":
                comparator.run_test("ask-hybrid", "Hybrid Search", question)

            elif choice == "3":
                comparator.run_test("ask-iterative", "Self-RAG Iterative", question)

            elif choice == "4":
                comparator.run_test("ask-smart", "Smart RAG", question)

            elif choice == "5":
                results = comparator.compare_all(question)
                comparator.print_comparison_table(results)

            elif choice == "6":
                print("\nSelect modes to compare (space-separated):")
                print("1=Standard 2=Hybrid 3=Iterative 4=Smart")
                selections = input("Your selection: ").strip().split()

                mode_map = {
                    "1": ("ask", "Standard RAG"),
                    "2": ("ask-hybrid", "Hybrid Search"),
                    "3": ("ask-iterative", "Self-RAG Iterative"),
                    "4": ("ask-smart", "Smart RAG")
                }

                custom_results = []
                for sel in selections:
                    if sel in mode_map:
                        endpoint, name = mode_map[sel]
                        result = comparator.run_test(endpoint, name, question)
                        custom_results.append(result)

                comparator.print_comparison_table(custom_results)

            elif choice == "7":
                comparator.print_comparison_table()

            elif choice == "8":
                stats = comparator.get_cache_stats()
                print(f"\n{Colors.CYAN}Cache Statistics:{Colors.END}")
                print(json.dumps(stats, indent=2))

            elif choice == "9":
                comparator.clear_cache()

            elif choice == "10":
                filename = input("Filename (default: rag_comparison_results.json): ").strip()
                comparator.export_results(filename or "rag_comparison_results.json")

            elif choice == "11":
                question = input(f"{Colors.CYAN}Enter new test question: {Colors.END}").strip()
                print(f"{Colors.GREEN}Test question updated{Colors.END}")

            elif choice == "0":
                print(f"{Colors.GREEN}Goodbye!{Colors.END}")
                break

            else:
                print(f"{Colors.RED}Invalid option{Colors.END}")

        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Interrupted by user{Colors.END}")
            break
        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.END}")

        input(f"\n{Colors.YELLOW}Press Enter to continue...{Colors.END}")


if __name__ == "__main__":
    main()
