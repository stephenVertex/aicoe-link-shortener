#!/bin/bash
# Test semantic search across AI-First Show video transcripts
# Demonstrates search quality by running curated queries and checking results

set -u

API_URL="https://dumhbtxskncofwwzrmfx.supabase.co/functions/v1/search-videos"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

pass_count=0
fail_count=0

run_search() {
    local query="$1"
    local expected_video_keywords="$2"
    local count="${3:-3}"
    
    echo -e "\n${BOLD}Query:${RESET} \"$query\"\n"
    
    result=$(curl -s -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -d "{\"query\": \"$query\", \"match_count\": $count, \"match_threshold\": 0.3}")
    
    echo "$result" | jq -r '.results[] | "  \(.video_title)\n     [\(.timestamp)] \(.text[:150])...\n     Score: \(.similarity | . * 100 | floor / 100)"' 2>/dev/null
    
    # Check if expected keywords appear in any result title or text
    if [ -n "$expected_video_keywords" ]; then
        if echo "$result" | jq -e "[.results[] | (.video_title + \" \" + .text)] | any(test(\"$expected_video_keywords\"; \"i\"))" >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ PASS${RESET}: Found expected content"
            ((pass_count++))
        else
            echo -e "  ${RED}✗ FAIL${RESET}: Expected content matching: $expected_video_keywords"
            ((fail_count++))
        fi
    else
        # No expectation, just verify we got results
        count_results=$(echo "$result" | jq '.results | length')
        if [ "$count_results" -gt 0 ]; then
            echo -e "  ${GREEN}✓ PASS${RESET}: Got $count_results results"
            ((pass_count++))
        else
            echo -e "  ${RED}✗ FAIL${RESET}: No results returned"
            ((fail_count++))
        fi
    fi
}

echo -e "${BOLD}========================================${RESET}"
echo -e "${BOLD}Semantic Video Search Test Suite${RESET}"
echo -e "${BOLD}========================================${RESET}"
echo -e "Testing search across AI-First Show video transcripts"
echo -e "API: $API_URL"

# Test 1: Conceptual search - AI impact on developers
run_search \
    "What does the team think about AI replacing developers" \
    "AI|developer|programming|commodit" \
    3

# Test 2: Technology-specific search - Cerebras
run_search \
    "Cerebras inference speed" \
    "Cerebras|inference" \
    3

# Test 3: Security topic
run_search \
    "prompt injection security vulnerabilities" \
    "injection|security|adversarial|sandbox" \
    3

# Test 4: Cost economics
run_search \
    "cost of running AI agents" \
    "cost|agent|API key|Prius" \
    3

# Test 5: MCP servers
run_search \
    "how to use MCP servers" \
    "MCP|tool|server" \
    3

# Test 6: Open vs closed source models
run_search \
    "open source AI models vs closed source" \
    "open|source|model|intelligence" \
    3

# Test 7: Agent orchestration
run_search \
    "agent orchestration swarms" \
    "agent|orchestr|swarm" \
    3

# Test 8: Model comparison and new releases
run_search \
    "new AI model releases Opus Codex GLM" \
    "Opus|Codex|GLM|model|Newborn" \
    3

echo -e "\n${BOLD}========================================${RESET}"
echo -e "${BOLD}Results: ${GREEN}$pass_count passed${RESET}, ${RED}$fail_count failed${RESET}"
echo -e "${BOLD}========================================${RESET}"

if [ $fail_count -gt 0 ]; then
    exit 1
fi
