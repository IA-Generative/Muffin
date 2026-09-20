#!/usr/bin/env bash
# Tests all tabular questions against the Muffin agent and reports results.
# Usage: ./tests-tabular/run-tests.sh [collection_id]
#
# Prerequisites:
#   - Docker services running (docker compose up -d)
#   - database.csv uploaded to the specified collection
#
# The script:
#   1. Gets a Keycloak token for the dev user
#   2. Finds the collection containing database.csv (or uses the one provided)
#   3. Sends each question and waits for the answer
#   4. Prints the answer alongside the expected answer for comparison

set -euo pipefail

BACKEND_URL="http://localhost:8000"
KEYCLOAK_URL="http://localhost:8080"
KEYCLOAK_REALM="muffin"
KEYCLOAK_CLIENT_ID="muffin-backend"
KEYCLOAK_CLIENT_SECRET="dev-only-secret-not-for-prod"
KEYCLOAK_USER="michou"
KEYCLOAK_PASS="muffin-dev"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}=== Muffin Tabular Tests ===${NC}"
echo ""

# ─── Step 1: Get Keycloak token ──────────────────────────────────────────────
echo -ne "Getting Keycloak token... "
TOKEN=$(curl -s -X POST \
  "${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=${KEYCLOAK_CLIENT_ID}" \
  -d "client_secret=${KEYCLOAK_CLIENT_SECRET}" \
  -d "username=${KEYCLOAK_USER}" \
  -d "password=${KEYCLOAK_PASS}" \
  -d "scope=openid profile email" \
  | jq -r '.access_token')

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo -e "${RED}FAILED${NC}"
  echo "Could not get Keycloak token. Make sure Keycloak is running on ${KEYCLOAK_URL}"
  exit 1
fi
echo -e "${GREEN}OK${NC}"

# ─── Step 2: Find the collection ──────────────────────────────────────────────
COLLECTION_ID="${1:-}"

if [ -z "$COLLECTION_ID" ]; then
  echo -ne "Finding collection with database.csv... "
  # List collections (paginated response: {items: [...], total: N})
  COLLECTIONS=$(curl -s -X GET \
    "${BACKEND_URL}/api/collections?size=50" \
    -H "Authorization: Bearer ${TOKEN}")

  COLLECTION_ID=$(echo "$COLLECTIONS" | jq -r '.items[0].id // empty')
  if [ -z "$COLLECTION_ID" ]; then
    echo -e "${RED}FAILED${NC}"
    echo "No collections found."
    echo "Response: $COLLECTIONS"
    exit 1
  fi
  COLLECTION_NAME=$(echo "$COLLECTIONS" | jq -r '.items[0].name // "unknown"')
  echo -e "${GREEN}${COLLECTION_NAME} (${COLLECTION_ID})${NC}"
else
  echo -e "Using collection: ${CYAN}${COLLECTION_ID}${NC}"
fi

# ─── Step 3: Define test questions ────────────────────────────────────────────
# Format: "question|||expected_answer_summary"
# The expected answer is just a keyword/number to check for, not an exact match
QUESTIONS=(
  "Combien y a-t-il de déclarants dans le fichier ?|||19"
  "Quel est le revenu fiscal de référence moyen ?|||15 308"
  "Quel est le revenu fiscal de référence le plus élevé ?|||37 023"
  "Quel est le revenu fiscal de référence le plus bas ?|||0"
  "Quelle est la répartition par situation de famille ?|||M.*5.*C.*4.*D.*6"
  "Quel est le revenu moyen par situation de famille ?|||C.*17 611"
  "Combien de déclarants sont nés dans chaque département ?|||25.*4"
  "Combien de déclarants ont un revenu supérieur à 20000 ?|||3"
  "Quels déclarants sont nés en 1962 ?|||STEPHANE DUPONT"
  "Combien de déclarants sont mariés ?|||5"
  "Quels déclarants ont plus de 3 personnes à charge ?|||MARCEL DOUZE"
  "Quels sont les 5 déclarants avec les revenus les plus élevés ?|||GUILLAUME DIX"
  "Quel est le revenu total cumulé par département de naissance ?|||67.*66 435"
  "Quel département a le revenu total le plus élevé ?|||67"
  "Quelle est la répartition par titre ?|||M.*12.*MME.*7"
  "Quel est le nombre maximum de personnes à charge ?|||9"
  "Quel est le revenu moyen des mariés vs célibataires ?|||13 254.*17 611"
  # ─── Complex questions (multi-step) ───────────────────────────────────────
  "Quel est le revenu moyen des déclarants nés dans le département 67 ?|||33 217"
  "Quel est le pourcentage de déclarants mariés ?|||26"
  "Quelle est la différence de revenu moyen entre les mariés et les célibataires ?|||4 357"
  "Quel est l'âge moyen des déclarants ?|||56"
  "Quels déclarants ont un revenu inférieur à 10000 ?|||SEBASTIEN TREIZE"
  "Quel est le revenu médian ?|||15 253"
  "Combien de déclarants ont plus de 2 personnes à charge ?|||10"
  "Quel est le revenu total de tous les déclarants ?|||275 560"
)

# ─── Step 4: Run tests ───────────────────────────────────────────────────────
PASS=0
FAIL=0
TOTAL=${#QUESTIONS[@]}

# Token refresh function - Keycloak tokens expire after ~5min, and 25 questions take longer
refresh_token() {
  TOKEN=$(curl -s -X POST \
    "${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=password" \
    -d "client_id=${KEYCLOAK_CLIENT_ID}" \
    -d "client_secret=${KEYCLOAK_CLIENT_SECRET}" \
    -d "username=${KEYCLOAK_USER}" \
    -d "password=${KEYCLOAK_PASS}" \
    -d "scope=openid profile email" \
    | jq -r '.access_token')
}

echo ""
echo -e "${CYAN}Running ${TOTAL} tests...${NC}"
echo ""

for i in "${!QUESTIONS[@]}"; do
  IFS='|||' read -r question expected <<< "${QUESTIONS[$i]}"
  qnum=$((i + 1))

  # Refresh token every 5 questions to avoid 401 errors
  if [ $((i % 5)) -eq 0 ] && [ $i -gt 0 ]; then
    refresh_token
  fi

  echo -ne "[$qnum/$TOTAL] ${question:0:60}... "

  # Create a run
  RUN_RESPONSE=$(curl -s -X POST \
    "${BACKEND_URL}/api/runs" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"${question}\", \"collection_ids\": [\"${COLLECTION_ID}\"]}")

  RUN_ID=$(echo "$RUN_RESPONSE" | jq -r '.id // empty')

  if [ -z "$RUN_ID" ]; then
    echo -e "${RED}FAILED (no run id)${NC}"
    FAIL=$((FAIL + 1))
    continue
  fi

  # Poll for completion (max 60 seconds)
  ANSWER=""
  for attempt in $(seq 1 60); do
    sleep 1
    RUN_STATUS=$(curl -s -X GET \
      "${BACKEND_URL}/api/runs/${RUN_ID}" \
      -H "Authorization: Bearer ${TOKEN}")

    STATUS=$(echo "$RUN_STATUS" | jq -r '.status // empty')
    ANSWER=$(echo "$RUN_STATUS" | jq -r '.answer // empty')

    if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
      break
    fi
  done

  if [ -z "$ANSWER" ]; then
    echo -e "${RED}FAILED (no answer, status: ${STATUS})${NC}"
    FAIL=$((FAIL + 1))
    continue
  fi

  # Check if the answer contains the expected keyword (case-insensitive, ignoring spaces)
  # Normalize: remove extra spaces for comparison
  ANSWER_NORM=$(echo "$ANSWER" | sed 's/[[:space:]]\+/ /g' | tr '[:upper:]' '[:lower:]')
  EXPECTED_NORM=$(echo "$expected" | sed 's/[[:space:]]\+/ /g' | tr '[:upper:]' '[:lower:]')

  # Use grep with regex for the expected pattern
  if echo "$ANSWER_NORM" | grep -qEi "$expected"; then
    echo -e "${GREEN}PASS${NC}"
    PASS=$((PASS + 1))
  else
    echo -e "${RED}FAIL${NC}"
    echo "  Expected pattern: $expected"
    echo "  Got: ${ANSWER:0:200}"
    FAIL=$((FAIL + 1))
  fi
done

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}=== Results ===${NC}"
echo -e "  ${GREEN}Passed: ${PASS}/${TOTAL}${NC}"
if [ "$FAIL" -gt 0 ]; then
  echo -e "  ${RED}Failed: ${FAIL}/${TOTAL}${NC}"
  exit 1
fi
echo -e "  ${GREEN}All tests passed!${NC}"
