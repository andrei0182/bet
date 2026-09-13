#!/bin/bash
# cleanup.sh — removes today's debug/test scratch files from disk (using
# plain rm, tolerant of files that may already be gone or never existed),
# then lets `git add -A` detect and stage the resulting deletions
# automatically — more robust than listing exact `git rm` pathspecs.
# Run from the repo root, then review with `git status` before committing.
set -e

echo "Removing debug/test files from disk..."
rm -f \
  chromedriver.log \
  debug_page.html debug_page.py \
  debug_page2.html debug_page2.py \
  league_curl.html \
  odds_curl.json \
  ou_curl.html ou_response.html \
  page_check.html \
  results_check.html \
  standalone_check.html \
  standings_component.html \
  run_log.txt run_log2.txt run_log3.txt run_log4.txt run_log5.txt run_final.txt run_final2.txt \
  test_1x2_endpoint.py test_1x2_endpoint2.py \
  test_bigmatch.py \
  test_click_debug.py test_click_new.py test_click_tab.py \
  test_completed_odds.py test_completed_odds2.py test_completed_odds3.py \
  test_league_page.py test_league_poll.py \
  test_ou_fetch.py \
  test_page_check.py \
  test_rate.py \
  test_speed.py \
  test_standalone_standings.py \
  test_standings_check.py test_standings_wait.py test_standings_wait2.py test_standings_wait3.py \
  test_stats.py test_stats_debug.py \
  test_ts_other_match.py test_ts_timing.py \
  test_xvfb.py

# Catch anything matching these patterns not explicitly listed above.
rm -f test_*.py *.html chromedriver.log odds_curl.json run_log*.txt run_final*.txt

echo ""
echo "Updating .gitignore..."
cat > .gitignore << 'EOF'
__pycache__/
*.pyc
output/*.xlsx
.venv/

# Session scratch/debug files — never commit these
test_*.py
debug_*.py
*.html
chromedriver.log
run_log*.txt
run_final*.txt
odds_curl.json
EOF

echo ""
echo "Staging everything (deletions + .gitignore update)..."
git add -A

echo ""
echo "Done. Review with 'git status', then:"
echo "  git commit -m 'Clean up debug/test scratch files, harden .gitignore'"
echo "  git push"
